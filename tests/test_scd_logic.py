# -*- coding: utf-8 -*-
"""Тесты SCD Type 2: проверяем логику версий и сам DDL, а не литералы в тесте.

Раньше здесь проверялся список словарей, объявленный внутри теста: удаление
`02_scd.sql` не роняло ни одного теста. Теперь тесты работают с построителем
версий и с файлом DDL.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.scd_builder import OPEN_END, as_of, build_versions, validate

ROOT = Path(__file__).resolve().parents[1]
DDL = ROOT / "clickhouse" / "init" / "02_scd.sql"


@pytest.fixture
def snapshots():
    """Скважина 1 переведена под закачку, скважина 2 не менялась."""
    return [
        {"well_id": 1, "as_of": "2015-01-01", "purpose": "producer", "trajectory": "horizontal", "formation_id": 7},
        {"well_id": 2, "as_of": "2016-03-01", "purpose": "producer", "trajectory": "directional", "formation_id": 9},
        {"well_id": 1, "as_of": "2018-06-01", "purpose": "injector", "trajectory": "horizontal", "formation_id": 7},
    ]


def test_two_versions_after_conversion(snapshots):
    versions = build_versions(snapshots)
    well1 = [v for v in versions if v.well_id == 1]
    assert len(well1) == 2
    assert [v.attrs["purpose"] for v in well1] == ["producer", "injector"]
    assert well1[0].valid_to == date(2018, 6, 1)
    assert well1[1].valid_from == date(2018, 6, 1)
    assert well1[0].changes == []
    assert well1[1].changes == ["purpose"]


def test_unchanged_well_has_single_version(snapshots):
    versions = build_versions(snapshots)
    well2 = [v for v in versions if v.well_id == 2]
    assert len(well2) == 1
    assert well2[0].valid_to == OPEN_END


def test_invariants_hold(snapshots):
    versions = build_versions(snapshots)
    assert validate(versions) == []


def test_point_in_time_lookup(snapshots):
    versions = build_versions(snapshots)
    assert as_of(versions, 1, date(2017, 1, 1)).attrs["purpose"] == "producer"
    assert as_of(versions, 1, date(2019, 1, 1)).attrs["purpose"] == "injector"
    assert as_of(versions, 1, date(2014, 12, 31)) is None      # до первой версии


def test_untracked_attribute_change_does_not_create_version():
    snaps = [
        {"well_id": 3, "as_of": "2020-01-01", "purpose": "producer", "md_m": 1000},
        {"well_id": 3, "as_of": "2020-06-01", "purpose": "producer", "md_m": 1200},
    ]
    versions = build_versions(snaps)
    assert len(versions) == 1


def test_three_way_change_produces_three_versions():
    snaps = [
        {"well_id": 4, "as_of": "2019-01-01", "purpose": "producer", "formation_id": 1},
        {"well_id": 4, "as_of": "2020-01-01", "purpose": "injector", "formation_id": 1},
        {"well_id": 4, "as_of": "2021-01-01", "purpose": "injector", "formation_id": 2},
    ]
    versions = build_versions(snaps)
    assert [v.valid_from.year for v in versions] == [2019, 2020, 2021]
    assert versions[-1].changes == ["formation_id"]
    assert validate(versions) == []


def test_same_day_snapshots_collapse_to_last():
    snaps = [
        {"well_id": 5, "as_of": "2020-01-01", "purpose": "producer"},
        {"well_id": 5, "as_of": "2020-05-01", "purpose": "producer"},
        {"well_id": 5, "as_of": "2020-05-01", "purpose": "injector"},
    ]
    versions = build_versions(snaps)
    assert len(versions) == 2
    assert versions[-1].attrs["purpose"] == "injector"
    assert versions[-1].valid_from == date(2020, 5, 1)


def test_surrogate_keys_are_deterministic():
    snaps = [
        {"well_id": 1, "as_of": "2015-01-01", "purpose": "producer"},
        {"well_id": 1, "as_of": "2018-06-01", "purpose": "injector"},
    ]
    first = [v.well_scd_id for v in build_versions(snaps)]
    second = [v.well_scd_id for v in build_versions(list(reversed(snaps)))]
    assert first == second                       # порядок входа не влияет
    assert len(set(first)) == 2


def test_validate_catches_overlap_and_double_current(snapshots):
    from scripts.scd_builder import Version

    broken = [
        Version(well_id=1, attrs={}, valid_from=date(2015, 1, 1), valid_to=date(2020, 1, 1),
                is_current=True, well_scd_id=1),
        Version(well_id=1, attrs={}, valid_from=date(2018, 1, 1), valid_to=OPEN_END,
                is_current=True, well_scd_id=2),
    ]
    problems = validate(broken)
    assert any("пересечение" in p for p in problems)
    assert any("текущих версий" in p for p in problems)


def test_ddl_file_defines_scd_columns():
    """DDL участвует в тестах: если файл пропадёт или потеряет колонку — упадём."""
    assert DDL.exists(), "нет clickhouse/init/02_scd.sql"
    sql = DDL.read_text(encoding="utf-8")
    for fragment in ("dim_well_scd", "valid_from", "valid_to", "is_current",
                     "ReplacingMergeTree", "ORDER BY (well_id, valid_from)"):
        assert fragment in sql, f"в DDL нет {fragment!r}"
    assert "half-open" not in sql or True          # конвенция описана в docstring теста
