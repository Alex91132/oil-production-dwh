# -*- coding: utf-8 -*-
"""Загрузка SCD Type 2: сравнивает текущие версии в ClickHouse с источником.

Разделено на две части:
  * `plan_changes` — чистая функция: что писать в таблицу (её и тестируем);
  * `apply_plan` — вставка в ClickHouse (та же логика, но с клиентом).

Схема работы на каждом запуске:
  1. в ClickHouse лежат текущие версии (`is_current = 1`);
  2. из PostgreSQL берём актуальные атрибуты скважин;
  3. если атрибут изменился — старая версия закрывается датой запуска,
     открывается новая с той же датой начала;
  4. если скважины ещё нет — создаётся первая версия.
"""

from __future__ import annotations

from datetime import date

from scripts.scd_builder import OPEN_END, surrogate_key

# Колонки в порядке DDL dwh.dim_well_scd
SCD_COLUMNS = [
    "well_scd_id", "well_id", "well_name",
    "field_id", "field_name", "region", "pad_id", "pad_name",
    "formation_id", "formation_name",
    "purpose", "trajectory",
    "spud_date", "start_date", "md_m",
    "valid_from", "valid_to", "is_current",
]

TRACKED = ("purpose", "trajectory", "formation_id")


def plan_changes(current: list[dict], source: list[dict], as_of: date,
                 tracked: tuple[str, ...] = TRACKED) -> list[dict]:
    """Возвращает строки для вставки: закрытие изменившихся версий и новые версии.

    `current` — текущие версии из ClickHouse (словари), `source` — строки из dim_well.
    Ничего не пишет и в БД не ходит, поэтому проверяется тестами без ClickHouse.
    """
    by_well = {int(row["well_id"]): row for row in current if row.get("is_current")}
    to_insert: list[dict] = []

    for row in source:
        well_id = int(row["well_id"])
        attrs = {name: row.get(name) for name in tracked}
        existing = by_well.get(well_id)

        if existing is None:
            to_insert.append(_version_row(row, valid_from=as_of, valid_to=OPEN_END,
                                          is_current=True))
            continue

        changed = [name for name in tracked if attrs[name] != existing.get(name)]
        if not changed:
            continue

        # Изменение в тот же день, когда версия открылась: закрывать её нельзя —
        # получится интервал нулевой длины. Обновляем атрибуты на месте.
        if _as_date(existing["valid_from"]) == as_of:
            updated = dict(existing)
            updated.update({name: row.get(name) for name in SCD_COLUMNS
                            if name not in ("well_scd_id", "valid_from", "valid_to", "is_current")})
            to_insert.append(_normalise(updated))
            continue

        closed = dict(existing)
        closed["valid_to"] = as_of
        closed["is_current"] = False
        to_insert.append(_normalise(closed))                 # та же версия, но закрытая

        to_insert.append(_version_row(row, valid_from=as_of, valid_to=OPEN_END,
                                      is_current=True))
    return to_insert


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _version_row(row: dict, valid_from: date, valid_to: date, is_current: bool) -> dict:
    """Собирает строку версии с детерминированным суррогатным ключом."""
    version = {name: row.get(name) for name in SCD_COLUMNS
               if name not in ("well_scd_id", "valid_from", "valid_to", "is_current")}
    version.update({
        "well_scd_id": surrogate_key(int(row["well_id"]), valid_from),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "is_current": is_current,
    })
    return _normalise(version)


def _normalise(row: dict) -> dict:
    """Приводит значение к тому, что примет ClickHouse (даты — ISO, bool — bool)."""
    out = {}
    for name in SCD_COLUMNS:
        value = row.get(name)
        if isinstance(value, date):
            value = value.isoformat()
        out[name] = value
    return out


def apply_plan(client, rows: list[dict], table: str = "dwh.dim_well_scd") -> int:
    """Пишет план в ClickHouse и схлопывает дубли ReplacingMergeTree.

    `OPTIMIZE ... FINAL` нужен, потому что дедупликация иначе асинхронная:
    без него в таблице временно лежат и старая, и новая версия строки.
    """
    if not rows:
        return 0
    client.insert(table, [tuple(row[name] for name in SCD_COLUMNS) for row in rows],
                  column_names=SCD_COLUMNS)
    client.command(f"OPTIMIZE TABLE {table} FINAL")
    return len(rows)


def fetch_current(client, table: str = "dwh.dim_well_scd") -> list[dict]:
    """Текущие версии из ClickHouse — для сравнения с источником."""
    result = client.query(f"SELECT * FROM {table} WHERE is_current = 1")
    names = result.column_names
    return [dict(zip(names, row)) for row in result.result_rows]
