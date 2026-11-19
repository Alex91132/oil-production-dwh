"""
### Загрузка хранилища нефтедобычи: PostgreSQL → ClickHouse

Один запуск DAG = один месяц данных (`data_interval_start` … `data_interval_end`),
запуск за месяц стартует после его окончания. История загружается автоматически
через `catchup` — по 3 месяца параллельно.

**Задачи запуска**
1. `refresh_reference` — полная перезаливка справочника скважин и фактов ГТМ
   (маленькие таблицы) с атомарной подменой через `EXCHANGE TABLES`.
2. `load_production`, `load_injection` — месяц суточных фактов собирается в
   промежуточной таблице и атомарно подменяет партицию (`REPLACE PARTITION`).
3. `build_mart` — витрина «месторождение × месяц» тем же способом.
4. `reconcile` — сверка с источником: число строк и точные суммы. При расхождении
   запуск падает.
5. `build_dim_well_scd` — SCD Type 2: сравнивает текущие версии атрибутов скважин
   с источником и закрывает/открывает версии при переводах под закачку и сменах пласта.
6. `profile_after_load` — профиль распределения `oil_t` (KS-тест) плюс сверки
   строк и сумм; при материальном расхождении запуск падает.

**Идемпотентность.** Каждая задача перезаписывает только «свою» месячную партицию,
поэтому повторный запуск и автоматические ретраи не создают дублей, а
параллельные запуски разных месяцев не мешают друг другу.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Connection, dag, get_current_context, task
from airflow.timetables.interval import CronDataIntervalTimetable

PG_CONN_ID = "oilfield_pg"
CH_CONN_ID = "clickhouse_dwh"

PRODUCTION_COLUMNS = ["prod_date", "well_id", "hours_on", "oil_t", "water_m3", "gas_km3"]
INJECTION_COLUMNS = ["inj_date", "well_id", "hours_on", "water_m3"]
WELL_COLUMNS = ["well_id", "well_name", "field_id", "field_name", "region", "pad_id", "pad_name",
                "formation_id", "formation_name", "oil_density", "purpose", "trajectory",
                "spud_date", "start_date", "md_m"]
INTERVENTION_COLUMNS = ["intervention_id", "well_id", "type_code", "type_name", "category",
                        "start_date", "end_date", "duration_days", "cost_mln_rub"]

WELLS_SQL = """
    SELECT w.well_id, w.name, f.field_id, f.name, f.region, p.pad_id, p.name,
           fm.formation_id, fm.name, fm.oil_density::float8, w.purpose::text, w.trajectory::text,
           w.spud_date, w.start_date, w.md_m::float8
    FROM ops.wells w
    JOIN ops.fields     f  ON f.field_id      = w.field_id
    JOIN ops.pads       p  ON p.pad_id        = w.pad_id
    JOIN ops.formations fm ON fm.formation_id = w.formation_id
    ORDER BY w.well_id
"""

INTERVENTIONS_SQL = """
    SELECT i.intervention_id, i.well_id, i.type_code, t.name_ru, t.category,
           i.start_date, i.end_date, i.end_date - i.start_date + 1, i.cost_mln_rub
    FROM ops.interventions i
    JOIN ops.intervention_types t USING (type_code)
    ORDER BY i.intervention_id
"""

MART_SQL = """
    INSERT INTO stg_mart_field_monthly
        (month, field_name, producing_wells, injecting_wells, oil_t, water_m3, gas_km3,
         liquid_m3, injection_m3, oil_t_per_day, watercut, compensation)
    WITH
        prod AS (
            SELECT
                w.field_name                                          AS field_name,
                uniqExactIf(p.well_id, p.hours_on > 0)                AS producing_wells,
                sum(p.oil_t)                                          AS oil_t,
                sum(p.water_m3)                                       AS water_m3,
                sum(p.gas_km3)                                        AS gas_km3,
                sum(toFloat64(p.oil_t) * 1000 / w.oil_density + toFloat64(p.water_m3)) AS liquid_m3
            FROM fact_production_daily AS p
            INNER JOIN dim_well AS w ON w.well_id = p.well_id
            WHERE p.prod_date >= {start:Date} AND p.prod_date < {end:Date}
            GROUP BY field_name
        ),
        inj AS (
            SELECT
                w.field_name                                          AS field_name,
                uniqExactIf(i.well_id, i.hours_on > 0)                AS injecting_wells,
                sum(i.water_m3)                                       AS injection_m3
            FROM fact_injection_daily AS i
            INNER JOIN dim_well AS w ON w.well_id = i.well_id
            WHERE i.inj_date >= {start:Date} AND i.inj_date < {end:Date}
            GROUP BY field_name
        )
    SELECT
        {start:Date},
        prod.field_name,
        prod.producing_wells,
        inj.injecting_wells,
        prod.oil_t,
        prod.water_m3,
        prod.gas_km3,
        prod.liquid_m3,
        inj.injection_m3,
        toFloat64(prod.oil_t) / dateDiff('day', {start:Date}, {end:Date}),
        if(prod.liquid_m3 > 0, toFloat64(prod.water_m3) / prod.liquid_m3, 0),
        if(prod.liquid_m3 > 0, toFloat64(inj.injection_m3) / prod.liquid_m3, 0)
    FROM prod
    LEFT JOIN inj USING (field_name)
"""


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def month_bounds():
    """Границы месяца текущего запуска: [start, end) и id партиции вида 202503."""
    ctx = get_current_context()
    start = ctx["data_interval_start"].date()
    end = ctx["data_interval_end"].date()
    if end <= start:
        # Защита от пустого интервала: иначе выборка вернёт 0 строк и тихо
        # «загрузит» пустой месяц
        raise ValueError(f"Пустой интервал данных {start} … {end}: у DAG должно быть "
                         "расписание с интервалами (CronDataIntervalTimetable)")
    return start, end, start.strftime("%Y%m")


def ch_client():
    import clickhouse_connect

    conn = Connection.get(CH_CONN_ID)
    return clickhouse_connect.get_client(
        host=conn.host, port=conn.port or 8123, username=conn.login,
        password=conn.password, database=conn.schema or "dwh")


def pg_fetch(sql, params=None):
    conn = PostgresHook(postgres_conn_id=PG_CONN_ID).get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def full_refresh(client, table, columns, rows, suffix):
    """Перезаливка небольшой таблицы: заполняем копию и атомарно меняем местами."""
    tmp = f"{table}_tmp_{suffix}"
    client.command(f"DROP TABLE IF EXISTS {tmp}")
    client.command(f"CREATE TABLE {tmp} AS {table}")
    client.insert(tmp, rows, column_names=columns)
    client.command(f"EXCHANGE TABLES {table} AND {tmp}")
    client.command(f"DROP TABLE {tmp}")


def replace_partition(client, fact, stage, partition, fill):
    """Собрать месяц в промежуточной таблице и атомарно подменить партицию факта."""
    client.command(f"ALTER TABLE {stage} DROP PARTITION {partition}")
    fill()
    # ClickHouse 26.8+ отказывается подменять партицию из пустого источника
    # (иначе молча сотрёт данные приёмника). Для идемпотентной перезагрузки месяца
    # без данных это как раз нужно: месяц пустой — партиция тоже должна стать пустой.
    client.command(
        f"ALTER TABLE {fact} REPLACE PARTITION {partition} FROM {stage} "
        "SETTINGS allow_replace_partition_from_empty_source = 1")
    client.command(f"ALTER TABLE {stage} DROP PARTITION {partition}")


def load_month(fact, stage, columns, source_sql):
    start, end, partition = month_bounds()
    rows = pg_fetch(source_sql, (start, end))
    client = ch_client()

    def fill():
        if rows:
            client.insert(stage, rows, column_names=columns)

    replace_partition(client, fact, stage, partition, fill)
    print(f"{fact}: партиция {partition} перезаписана, строк {len(rows)}")
    return len(rows)


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------

@dag(
    dag_id="oil_dwh_monthly_load",
    # Явно «интервальное» расписание. В Airflow 3 строка "@monthly" по умолчанию
    # даёт запуски без интервала данных (start == end), а нам нужны границы месяца:
    # запуск за январь стартует 1 февраля и грузит [1 янв, 1 фев).
    schedule=CronDataIntervalTimetable("@monthly", timezone=pendulum.UTC),
    start_date=pendulum.datetime(2021, 1, 1, tz="UTC"),
    end_date=pendulum.datetime(2026, 9, 30, tz="UTC"),
    catchup=True,
    max_active_runs=3,
    default_args={"retries": 2, "retry_delay": timedelta(seconds=30)},
    tags=["dwh", "clickhouse", "postgres"],
    doc_md=__doc__,
)
def oil_dwh_monthly_load():

    @task
    def refresh_reference():
        _, _, partition = month_bounds()
        client = ch_client()
        full_refresh(client, "dim_well", WELL_COLUMNS, pg_fetch(WELLS_SQL), partition)
        full_refresh(client, "fact_interventions", INTERVENTION_COLUMNS,
                     pg_fetch(INTERVENTIONS_SQL), partition)

    @task
    def load_production() -> int:
        return load_month(
            "fact_production_daily", "stg_production_daily", PRODUCTION_COLUMNS,
            f"SELECT {', '.join(PRODUCTION_COLUMNS)} FROM ops.daily_production "
            "WHERE prod_date >= %s AND prod_date < %s")

    @task
    def load_injection() -> int:
        return load_month(
            "fact_injection_daily", "stg_injection_daily", INJECTION_COLUMNS,
            f"SELECT {', '.join(INJECTION_COLUMNS)} FROM ops.daily_injection "
            "WHERE inj_date >= %s AND inj_date < %s")

    @task
    def build_mart():
        start, end, partition = month_bounds()
        client = ch_client()
        replace_partition(
            client, "mart_field_monthly", "stg_mart_field_monthly", partition,
            lambda: client.command(MART_SQL, parameters={"start": start, "end": end}))

    @task
    def reconcile(production_rows: int, injection_rows: int):
        """Источник и хранилище должны совпасть до последнего знака."""
        start, end, _ = month_bounds()
        client = ch_client()
        params = {"start": start, "end": end}
        checks = {
            "добыча: строки и суммы": (
                pg_fetch("""SELECT count(*), coalesce(sum(oil_t), 0), coalesce(sum(water_m3), 0),
                                   coalesce(sum(gas_km3), 0)
                            FROM ops.daily_production
                            WHERE prod_date >= %s AND prod_date < %s""", (start, end))[0],
                client.query("""SELECT count(), sum(oil_t), sum(water_m3), sum(gas_km3)
                                FROM fact_production_daily
                                WHERE prod_date >= {start:Date} AND prod_date < {end:Date}""",
                             parameters=params).result_rows[0]),
            "закачка: строки и сумма": (
                pg_fetch("""SELECT count(*), coalesce(sum(water_m3), 0) FROM ops.daily_injection
                            WHERE inj_date >= %s AND inj_date < %s""", (start, end))[0],
                client.query("""SELECT count(), sum(water_m3) FROM fact_injection_daily
                                WHERE inj_date >= {start:Date} AND inj_date < {end:Date}""",
                             parameters=params).result_rows[0]),
            "витрина = факт по нефти": (
                client.query("""SELECT sum(oil_t) FROM fact_production_daily
                                WHERE prod_date >= {start:Date} AND prod_date < {end:Date}""",
                             parameters=params).result_rows[0],
                client.query("SELECT sum(oil_t) FROM mart_field_monthly WHERE month = {start:Date}",
                             parameters=params).result_rows[0]),
        }
        failed = {name: (src, dst) for name, (src, dst) in checks.items() if tuple(src) != tuple(dst)}
        for name, (src, dst) in checks.items():
            print(f"{'OK ' if name not in failed else 'ОШИБКА'} {name}: источник {tuple(src)}, хранилище {tuple(dst)}")
        if failed:
            raise ValueError(f"Расхождение с источником за {start:%Y-%m}: {failed}")
        print(f"Сверка за {start:%Y-%m} пройдена: добыча {production_rows} строк, закачка {injection_rows} строк")

    @task
    def build_dim_well_scd():
        """SCD Type 2: снимок атрибутов скважин на дату запуска.

        Исторического источника атрибутов нет — и Postgres, и ClickHouse хранят
        текущее состояние. Поэтому дата версии — день запуска, а не месяц данных.
        Повторный запуск за прошлый месяц ничего не меняет: план сравнивает текущие
        версии с источником и при отсутствии изменений возвращает пустой список.
        """
        from scripts.scd_loader import apply_plan, fetch_current, plan_changes

        client = ch_client()
        source = [dict(zip(WELL_COLUMNS, row)) for row in pg_fetch(WELLS_SQL)]
        current = fetch_current(client)
        rows = plan_changes(current, source, pendulum.now("UTC").date())
        inserted = apply_plan(client, rows)
        print(f"dim_well_scd: скважин в источнике {len(source)}, текущих версий "
              f"{len(current)}, новых строк {inserted}")

    @task
    def profile_after_load():
        """Профиль распределений и сверки за месяц — то, чего не видит reconcile."""
        import numpy as np

        from scripts.quality_gate import build_checks, report

        start, end, _ = month_bounds()
        client = ch_client()
        params = {"start": start, "end": end}
        src_rows = pg_fetch("""SELECT oil_t FROM ops.daily_production
                               WHERE prod_date >= %s AND prod_date < %s""", (start, end))
        tgt_rows = client.query("""SELECT oil_t FROM fact_production_daily
                                   WHERE prod_date >= {start:Date} AND prod_date < {end:Date}""",
                                parameters=params).result_rows
        source_values = np.array([float(r[0]) for r in src_rows], dtype=float)
        target_values = np.array([float(r[0]) for r in tgt_rows], dtype=float)

        verdict = build_checks(
            column="oil_t",
            source_values=source_values, target_values=target_values,
            source_rows=len(src_rows), target_rows=len(tgt_rows),
            source_sum=float(source_values.sum()), target_sum=float(target_values.sum()),
        )
        print(report(verdict))
        if not verdict["passed"]:
            raise ValueError("контроль качества не пройден: " + "; ".join(verdict["failures"]))

    reference = refresh_reference()
    scd = build_dim_well_scd()
    production = load_production()
    injection = load_injection()
    mart = build_mart()

    reference >> scd
    [reference, production, injection] >> mart
    reconcile_task = reconcile(production, injection)
    mart >> reconcile_task
    reconcile_task >> profile_after_load()


oil_dwh_monthly_load()
