"""
Генератор синтетических данных нефтедобычи для схемы ops.

Модель:
  * дебит жидкости падает по гиперболе Арпса: q(t) = q0 / (1 + b*Di*t)^(1/b);
  * обводнённость растёт по логистической кривой;
  * ГТМ дают прирост дебита, затухающий экспонентой; РИР снижает обводнённость;
    ЗБС «перезапускает» скважину с новым стартовым дебитом;
  * случайные простои, частичная отработка суток;
  * скважина выбывает, когда потенциал по нефти падает ниже экономического предела.

Все названия вымышлены, данные синтетические. Результат детерминирован (--seed).

Подключение берётся из переменных окружения PGHOST, PGPORT, PGUSER, PGPASSWORD,
PGDATABASE (или из аргументов командной строки).
"""

import argparse
import io
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import psycopg2
from psycopg2.extras import execute_values

START = date(2021, 1, 1)
END = date(2026, 9, 30)
N_DAYS = (END - START).days + 1

ECONOMIC_LIMIT_T = 0.8          # т/сут нефти — ниже скважина выбывает
TRAJECTORY_MULT = {"directional": 1.0, "horizontal": 2.0, "multilateral": 2.8}
TRAJECTORY_SUFFIX = {"directional": "", "horizontal": "Г", "multilateral": "М"}
DRILL_DAYS = {"directional": (14, 20), "horizontal": (22, 30), "multilateral": (28, 38)}

# Месторождение: название, регион, год открытия, центр (lat, lon),
# годы разбуривания кустов, пласты (индекс, кровля м, пористость, проницаемость мД, плотность нефти)
FIELDS = [
    ("Кедровое", "ХМАО-Югра", 1984, (61.20, 72.50), (2013, 2018),
     [("БС10", 2350, 0.21, 45, 860), ("ЮС1", 2780, 0.17, 8, 845)]),
    ("Озёрное", "ЯНАО", 1991, (64.10, 76.30), (2015, 2022),
     [("БП12", 2620, 0.20, 30, 850), ("Ач3", 2950, 0.16, 4, 835)]),
    ("Таёжное", "Красноярский край", 2004, (67.60, 86.40), (2019, 2025),
     [("АВ1", 1950, 0.25, 250, 890), ("БВ8", 2180, 0.23, 120, 875), ("ЮВ1", 2450, 0.19, 15, 855)]),
]
RIGS = [("БУ-1", "Подрядчик А"), ("БУ-2", "Подрядчик Б"), ("БУ-3", "Подрядчик В")]


@dataclass
class Well:
    field_idx: int
    pad_idx: int
    formation_idx: int
    name: str
    purpose: str
    trajectory: str
    spud_date: date
    start_date: date
    md_m: float
    well_id: int = 0


@dataclass
class Event:
    type_code: str
    start: int            # индекс дня в окне данных
    end: int
    cost: float
    params: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Структура месторождений и график бурения
# ---------------------------------------------------------------------------

def build_structure(rng):
    """Кусты, расписание буровых и скважины."""
    pads = []          # (field_idx, name, lat, lon, planned_date, n_wells)
    for fi, (_, _, _, (lat0, lon0), (y0, y1), _) in enumerate(FIELDS):
        n_pads = int(rng.integers(12, 17))
        span = (date(y1, 6, 30) - date(y0, 1, 1)).days
        for k in range(n_pads):
            planned = date(y0, 1, 1) + timedelta(days=int(span * k / n_pads + rng.integers(0, 60)))
            pads.append(dict(field_idx=fi, name=f"Куст {k + 1}",
                             lat=lat0 + rng.uniform(-0.15, 0.15),
                             lon=lon0 + rng.uniform(-0.25, 0.25),
                             planned=planned, n_wells=int(rng.integers(6, 15)), no=k + 1))

    # Жадное расписание: куст забирает буровая, которая освободится раньше всех
    rig_free = [date(2012, 6, 1)] * len(RIGS)
    assignments, wells = [], []
    for pad_idx, pad in sorted(enumerate(pads), key=lambda p: p[1]["planned"]):
        rig = int(np.argmin([d.toordinal() for d in rig_free]))
        move = int(rng.integers(5, 16))                      # переезд и монтаж
        start = max(rig_free[rig] + timedelta(days=move), pad["planned"])
        if start > END:
            pad["skipped"] = True
            continue
        n_formations = len(FIELDS[pad["field_idx"]][5])
        cursor = start
        for seq in range(1, pad["n_wells"] + 1):
            traj = rng.choice(["directional", "horizontal", "multilateral"], p=[0.45, 0.4, 0.15])
            purpose = "producer" if rng.random() < 0.8 else "injector"
            fm_idx = int(rng.integers(0, n_formations))
            top = FIELDS[pad["field_idx"]][5][fm_idx][1]
            lo, hi = DRILL_DAYS[traj]
            drill = int(rng.integers(lo, hi + 1))
            spud = cursor
            if spud > END:
                break
            md = top * 1.15 + {"directional": 0, "horizontal": rng.uniform(600, 1200),
                               "multilateral": rng.uniform(1200, 2500)}[traj]
            wells.append(Well(pad["field_idx"], pad_idx, fm_idx,
                              f"{pad['no']}{seq:02d}{TRAJECTORY_SUFFIX[traj]}",
                              purpose, traj, spud,
                              spud + timedelta(days=drill + int(rng.integers(10, 26))),
                              round(md, 1)))
            cursor = spud + timedelta(days=drill)
        end = min(cursor, END)
        assignments.append((rig, pad_idx, start, end))
        rig_free[rig] = cursor
    return pads, assignments, wells


# ---------------------------------------------------------------------------
# Моделирование добычи
# ---------------------------------------------------------------------------

def arps(q0, age_years, b, di):
    return q0 / np.power(1.0 + b * di * age_years, 1.0 / b)


def logistic_wc(age_years, wc0, wc_max, t50, k):
    return wc0 + (wc_max - wc0) / (1.0 + np.exp(-k * (age_years - t50)))


def apply_downtime(rng, hours, years):
    """Случайные аварийные простои и неполные сутки."""
    n = len(hours)
    for _ in range(rng.poisson(1.2 * max(years, 0.1))):
        s = int(rng.integers(0, n))
        dur = min(1 + int(rng.geometric(0.25)), 40)
        hours[s:s + dur] = 0.0
    partial = rng.random(n) < 0.08
    hours[partial] = np.minimum(hours[partial], rng.uniform(6, 23, partial.sum()))
    return hours


def plan_events(rng, s, base_age_days, base_wc, base_oil_pot):
    """Расписание ГТМ по скважине. Решение о мероприятии принимается по базовой кривой."""
    events, busy_until, sidetracked = [], -1, False
    for d in range(s + 60, N_DAYS - 60, 30):               # «совещание по ГТМ» раз в месяц
        if d <= busy_until:
            continue
        i = d - s
        age_y = base_age_days[i] / 365.25
        candidates = [("PUMP", 0.30 / 12)]
        candidates.append(("ACID", 0.10 / 12))
        if age_y > 1.5:
            candidates.append(("FRAC", 0.08 / 12))
        if base_wc[i] > 0.8:
            candidates.append(("WSO", 0.08 / 12))
        if age_y > 6 and base_oil_pot[i] < 8 and not sidetracked:
            candidates.append(("SIDETRACK", 0.15 / 12))
        for code, p in candidates:
            if rng.random() >= p:
                continue
            if code == "PUMP":
                # отказ насоса: перед заменой он изнашивается и дебит проседает
                dur, cost = rng.integers(3, 8), rng.uniform(2, 5)
                prm = dict(m=rng.uniform(1.0, 1.1), tau=rng.uniform(60, 200), wear=rng.uniform(0.15, 0.4))
            elif code == "ACID":
                dur, cost, prm = rng.integers(2, 6), rng.uniform(1, 3), dict(m=rng.uniform(1.05, 1.5), tau=rng.uniform(60, 200))
            elif code == "FRAC":
                ok = rng.random() > 0.15
                dur, cost = rng.integers(7, 15), rng.uniform(8, 15)
                prm = dict(m=rng.uniform(1.3, 3.0) if ok else rng.uniform(0.95, 1.1), tau=rng.uniform(180, 600))
            elif code == "WSO":
                ok = rng.random() > 0.25
                dur, cost = rng.integers(5, 11), rng.uniform(3, 6)
                prm = dict(r=rng.uniform(0.1, 0.4) if ok else rng.uniform(0.0, 0.05), tau=rng.uniform(120, 400))
            else:  # SIDETRACK
                dur, cost, prm = rng.integers(30, 51), rng.uniform(40, 70), dict(q_mult=rng.uniform(0.6, 1.0))
                sidetracked = True
            end = min(d + int(dur) - 1, N_DAYS - 1)
            events.append(Event(code, d, end, round(float(cost), 2), prm))
            busy_until = end + 45                          # между ГТМ минимум полтора месяца
            break
    return events


def simulate_producer(rng, well, fm):
    """Возвращает (индексы дней, часы, нефть т, вода м3, газ тыс.м3) и список ГТМ."""
    offset = (well.start_date - START).days               # < 0, если введена до окна
    s = max(0, offset)
    if s >= N_DAYS:
        return None, []
    idx = np.arange(s, N_DAYS)
    age_days = (idx - offset).astype(float)

    _, _, porosity, perm, density = fm
    # Дебит жидкости падает медленно; падение нефти в основном даёт рост обводнённости
    q0 = 40 * (perm / 30) ** 0.5 * TRAJECTORY_MULT[well.trajectory] * rng.lognormal(0, 0.35)
    b, di = rng.uniform(0.3, 0.8), rng.uniform(0.05, 0.25)
    wc0, wc_max, t50, k = rng.uniform(0.03, 0.25), rng.uniform(0.90, 0.98), rng.uniform(2.5, 8), rng.uniform(0.5, 1.1)
    gor = rng.uniform(50, 140)                               # газовый фактор, м3/т

    base_liq = arps(q0, age_days / 365.25, b, di)
    base_wc = logistic_wc(age_days / 365.25, wc0, wc_max, t50, k)
    base_oil = base_liq * (1 - base_wc) * density / 1000
    events = plan_events(rng, s, age_days, base_wc, base_oil)

    # Применяем эффекты мероприятий
    age_eff = age_days / 365.25
    q0_arr = np.full(len(idx), q0)
    wc0_arr, t50_arr = np.full(len(idx), wc0), np.full(len(idx), t50)
    mult = np.ones(len(idx))
    wc_factor = np.ones(len(idx))
    for e in events:
        after = idx > e.end
        dt = (idx[after] - e.end).astype(float)
        if e.type_code == "PUMP":                          # износ за 60 суток до отказа
            wearing = (idx >= e.start - 60) & (idx < e.start)
            ramp = 1 - (e.start - idx[wearing]) / 60.0
            mult[wearing] *= 1 - e.params["wear"] * ramp
        if e.type_code in ("PUMP", "ACID", "FRAC"):
            mult[after] *= 1 + (e.params["m"] - 1) * np.exp(-dt / e.params["tau"])
        elif e.type_code == "WSO":
            wc_factor[after] *= 1 - e.params["r"] * np.exp(-dt / e.params["tau"])
        elif e.type_code == "SIDETRACK":                   # новый ствол: возраст обнуляется
            age_eff[after] = dt / 365.25
            q0_arr[after] = q0 * e.params["q_mult"]
            wc0_arr[after] = rng.uniform(0.2, 0.5)         # вскрывается частично обводнённая зона
            t50_arr[after] = rng.uniform(2, 5)

    liquid = arps(q0_arr, age_eff, b, di) * mult
    wc = np.clip(logistic_wc(age_eff, wc0_arr, wc_max, t50_arr, k) * wc_factor, 0, 0.99)
    oil_pot = liquid * (1 - wc) * density / 1000

    # Выбытие по экономическому пределу (не раньше двух лет работы)
    below = np.nonzero((oil_pot < ECONOMIC_LIMIT_T) & (age_days > 730))[0]
    n = below[0] if len(below) else len(idx)
    if n == 0:
        return None, []
    idx, liquid, wc = idx[:n], liquid[:n], wc[:n]
    events = [e for e in events if e.start < idx[-1]]

    hours = apply_downtime(rng, np.full(n, 24.0), n / 365.25)
    for e in events:                                        # во время ГТМ скважина стоит
        hours[max(e.start - s, 0):e.end - s + 1] = 0.0

    liquid = liquid * rng.lognormal(0, 0.06, n) * hours / 24
    oil = liquid * (1 - wc) * density / 1000
    water = liquid * wc
    gas = oil * gor * rng.lognormal(0, 0.05, n) / 1000
    return (idx, hours, oil, water, gas), events


def simulate_injector(rng, well):
    offset = (well.start_date - START).days
    s = max(0, offset)
    if s >= N_DAYS:
        return None
    idx = np.arange(s, N_DAYS)
    n = len(idx)
    base = rng.uniform(120, 420)
    seasonal = 1 + 0.15 * np.sin(2 * np.pi * idx / 365.25 + rng.uniform(0, 2 * np.pi))
    hours = apply_downtime(rng, np.full(n, 24.0), n / 365.25)
    water = base * seasonal * rng.lognormal(0, 0.08, n) * hours / 24
    return idx, hours, water


# ---------------------------------------------------------------------------
# Загрузка в PostgreSQL
# ---------------------------------------------------------------------------

def connect(args):
    params = dict(host=args.host, port=args.port, user=args.user,
                  password=args.password, dbname=args.dbname)
    attempts = 60 if args.wait else 1
    for attempt in range(1, attempts + 1):
        try:
            return psycopg2.connect(**params)
        except psycopg2.OperationalError as exc:
            if attempt == attempts:
                raise
            print(f"БД ещё недоступна ({exc.__class__.__name__}), повтор через 2 с…", flush=True)
            time.sleep(2)


def copy_rows(cur, table, columns, lines):
    buf = io.StringIO("\n".join(lines) + "\n")
    cur.copy_expert(f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv)", buf)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.getenv("PGHOST", "localhost"))
    ap.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5435")))
    ap.add_argument("--user", default=os.getenv("PGUSER", "dwh"))
    ap.add_argument("--password", default=os.getenv("PGPASSWORD", "dwh"))
    ap.add_argument("--dbname", default=os.getenv("PGDATABASE", "oilfield"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--force", action="store_true", help="очистить таблицы и сгенерировать заново")
    ap.add_argument("--wait", action="store_true", help="ждать готовности БД (для docker compose)")
    args = ap.parse_args()

    conn = connect(args)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM ops.wells")
    if cur.fetchone()[0] > 0 and not args.force:
        print("Данные уже загружены. Для перегенерации запустите с --force.")
        return
    if args.force:
        cur.execute("""TRUNCATE ops.daily_production, ops.daily_injection, ops.interventions,
                       ops.rig_assignments, ops.wells, ops.pads, ops.formations,
                       ops.fields, ops.rigs RESTART IDENTITY CASCADE""")

    t0 = time.time()
    rng = np.random.default_rng(args.seed)
    pads, assignments, wells = build_structure(rng)

    # --- справочники и структура (небольшие таблицы, нужны сгенерированные id)
    field_ids, formation_ids = [], []
    for name, region, disc, _, _, formations in FIELDS:
        cur.execute("INSERT INTO ops.fields (name, region, discovered) VALUES (%s, %s, %s) RETURNING field_id",
                    (name, region, disc))
        fid = cur.fetchone()[0]
        field_ids.append(fid)
        ids = []
        for fm_name, top, por, perm, dens in formations:
            cur.execute("""INSERT INTO ops.formations
                           (field_id, name, top_depth_m, porosity, permeability_md, oil_density)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING formation_id""",
                        (fid, fm_name, top, por, perm, dens))
            ids.append(cur.fetchone()[0])
        formation_ids.append(ids)

    pad_ids = {}
    for i, p in enumerate(pads):
        if p.get("skipped"):
            continue
        cur.execute("INSERT INTO ops.pads (field_id, name, lat, lon) VALUES (%s, %s, %s, %s) RETURNING pad_id",
                    (field_ids[p["field_idx"]], p["name"], round(p["lat"], 5), round(p["lon"], 5)))
        pad_ids[i] = cur.fetchone()[0]

    rig_ids = []
    for name, contractor in RIGS:
        cur.execute("INSERT INTO ops.rigs (name, contractor) VALUES (%s, %s) RETURNING rig_id", (name, contractor))
        rig_ids.append(cur.fetchone()[0])
    execute_values(cur, "INSERT INTO ops.rig_assignments (rig_id, pad_id, start_date, end_date) VALUES %s",
                   [(rig_ids[r], pad_ids[p], s, e) for r, p, s, e in assignments])

    for w in wells:
        cur.execute("""INSERT INTO ops.wells (field_id, pad_id, formation_id, name, purpose, trajectory,
                                              spud_date, start_date, md_m)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING well_id""",
                    (field_ids[w.field_idx], pad_ids[w.pad_idx], formation_ids[w.field_idx][w.formation_idx],
                     w.name, w.purpose, w.trajectory, w.spud_date, w.start_date, w.md_m))
        w.well_id = cur.fetchone()[0]

    # --- моделирование
    date_str = [(START + timedelta(days=d)).isoformat() for d in range(N_DAYS)]
    prod_parts, inj_parts, interventions = [], [], []
    for w in wells:
        if w.purpose == "producer":
            fm = FIELDS[w.field_idx][5][w.formation_idx]
            series, events = simulate_producer(rng, w, fm)
            if series is not None:
                prod_parts.append((np.full(len(series[0]), w.well_id),) + series)
            for e in events:
                interventions.append((w.well_id, e.type_code, date_str[e.start], date_str[e.end], e.cost))
        else:
            series = simulate_injector(rng, w)
            if series is not None:
                inj_parts.append((np.full(len(series[0]), w.well_id),) + series)

    # --- суточная добыча: сортируем по дате, чтобы физический порядок строк
    #     совпадал с хронологией (на этом держится эффективность BRIN-индекса)
    wid, idx, hours, oil, water, gas = (np.concatenate(c) for c in zip(*prod_parts))
    order = np.lexsort((wid, idx))
    lines = [f"{wid[i]},{date_str[idx[i]]},{hours[i]:.1f},{oil[i]:.3f},{water[i]:.3f},{gas[i]:.3f}"
             for i in order]
    copy_rows(cur, "ops.daily_production",
              ["well_id", "prod_date", "hours_on", "oil_t", "water_m3", "gas_km3"], lines)

    wid, idx, hours, water = (np.concatenate(c) for c in zip(*inj_parts))
    order = np.lexsort((wid, idx))
    lines = [f"{wid[i]},{date_str[idx[i]]},{hours[i]:.1f},{water[i]:.3f}" for i in order]
    copy_rows(cur, "ops.daily_injection", ["well_id", "inj_date", "hours_on", "water_m3"], lines)

    execute_values(cur, """INSERT INTO ops.interventions (well_id, type_code, start_date, end_date, cost_mln_rub)
                           VALUES %s""", interventions)

    cur.execute("REFRESH MATERIALIZED VIEW ops.mv_monthly_production")
    conn.commit()

    conn.autocommit = True                                   # VACUUM нельзя внутри транзакции
    cur.execute("VACUUM ANALYZE")

    cur.execute("""SELECT (SELECT count(*) FROM ops.fields), (SELECT count(*) FROM ops.pads),
                          (SELECT count(*) FROM ops.wells), (SELECT count(*) FROM ops.daily_production),
                          (SELECT count(*) FROM ops.daily_injection), (SELECT count(*) FROM ops.interventions),
                          (SELECT count(*) FROM ops.rig_assignments)""")
    f, p, w, dp, di, iv, ra = cur.fetchone()
    num = lambda x: f"{x:,}".replace(",", " ")
    print(f"Готово за {time.time() - t0:.1f} с: месторождений {f}, кустов {p}, скважин {w}, "
          f"строк добычи {num(dp)}, строк закачки {num(di)}, ГТМ {iv}, назначений буровых {ra}")
    conn.close()


if __name__ == "__main__":
    sys.exit(main())
