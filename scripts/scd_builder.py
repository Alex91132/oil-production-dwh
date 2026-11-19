# -*- coding: utf-8 -*-
"""Построение версий SCD Type 2 из снимков измерения.

Загрузчика в DAG пока нет, но логика версий — самая опасная часть SCD, и её
можно проверить без ClickHouse: на вход снимки (когда какой атрибут был каким),
на выходе строки с `valid_from` / `valid_to` / `is_current`.

Правила:
  * интервал полуоткрытый: `valid_from <= d < valid_to`;
  * версия закрывается в дату изменения, новая начинается в ту же дату;
  * неизменившиеся снимки не создают версий;
  * если на одну дату пришло несколько снимков — берём последний;
  * `well_scd_id` детерминирован (sha1 от ключа и даты), чтобы повторный прогон
    не плодил новые версии.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

TRACKED_ATTRS = ("purpose", "trajectory", "formation_id")
# Date32 в ClickHouse: верхняя граница 2299 год, 9999 туда не помещается
OPEN_END = date(2299, 12, 31)


@dataclass
class Version:
    well_id: int
    attrs: dict
    valid_from: date
    valid_to: date = OPEN_END
    is_current: bool = True
    well_scd_id: int = 0
    changes: list[str] = field(default_factory=list)   # какие атрибуты изменились


def surrogate_key(well_id: int, valid_from: date) -> int:
    """Детерминированный суррогатный ключ версии (не зависит от порядка строк)."""
    raw = f"{well_id}|{valid_from.isoformat()}".encode("utf-8")
    return int(hashlib.sha1(raw).hexdigest()[:15], 16)


def build_versions(snapshots: list[dict], tracked: tuple[str, ...] = TRACKED_ATTRS) -> list[Version]:
    """Собирает версии SCD2 из снимков.

    Снимок: {"well_id": 1, "as_of": "2015-01-01", "purpose": "producer", ...}
    Остальные ключи считаются атрибутами и копируются в версию.
    """
    if not snapshots:
        return []

    # 1. группируем по скважине, на одну дату — последний снимок
    by_well: dict[int, dict[date, dict]] = {}
    for row in snapshots:
        well_id = int(row["well_id"])
        as_of = _as_date(row["as_of"])
        by_well.setdefault(well_id, {})[as_of] = row

    versions: list[Version] = []
    for well_id, dated in by_well.items():
        ordered = sorted(dated.items())                      # по дате
        current: Version | None = None
        for as_of, snapshot in ordered:
            attrs = {k: v for k, v in snapshot.items() if k not in ("well_id", "as_of")}
            if current is None:
                current = Version(well_id=well_id, attrs=dict(attrs), valid_from=as_of)
                current.well_scd_id = surrogate_key(well_id, as_of)
                versions.append(current)
                continue

            changed = [name for name in tracked
                       if name in attrs and attrs[name] != current.attrs.get(name)]
            if not changed:
                continue

            current.valid_to = as_of          # закрываем предыдущую версию
            current.is_current = False
            new_version = Version(well_id=well_id, attrs=dict(attrs), valid_from=as_of,
                                  changes=changed)
            new_version.well_scd_id = surrogate_key(well_id, as_of)
            versions.append(new_version)
            current = new_version

    return sorted(versions, key=lambda v: (v.well_id, v.valid_from))


def as_of(versions: list[Version], well_id: int, when: date) -> Version | None:
    """Point-in-time lookup: какая версия действовала на дату."""
    for version in versions:
        if version.well_id == well_id and version.valid_from <= when < version.valid_to:
            return version
    return None


def validate(versions: list[Version]) -> list[str]:
    """Проверяет инварианты SCD2. Возвращает список нарушений (пустой — всё хорошо)."""
    problems: list[str] = []
    by_well: dict[int, list[Version]] = {}
    for version in versions:
        by_well.setdefault(version.well_id, []).append(version)

    for well_id, items in by_well.items():
        items = sorted(items, key=lambda v: v.valid_from)
        current = [v for v in items if v.is_current]
        if len(current) != 1:
            problems.append(f"well {well_id}: {len(current)} текущих версий вместо одной")
        if current and current[0] is not items[-1]:
            problems.append(f"well {well_id}: текущая версия не последняя по дате")
        for left, right in zip(items, items[1:]):
            if left.valid_to > right.valid_from:
                problems.append(f"well {well_id}: пересечение {left.valid_to} > {right.valid_from}")
            if left.valid_to != right.valid_from:
                problems.append(f"well {well_id}: разрыв {left.valid_to} → {right.valid_from}")
        if items and items[-1].valid_to != OPEN_END:
            problems.append(f"well {well_id}: последняя версия закрыта ({items[-1].valid_to})")

    ids = [v.well_scd_id for v in versions]
    if len(ids) != len(set(ids)):
        problems.append("суррогатные ключи повторяются")
    return problems


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
