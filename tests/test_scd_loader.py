# -*- coding: utf-8 -*-
"""Тесты загрузчика SCD и контроля качества: без ClickHouse, на чистых функциях."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from scripts.quality_gate import build_checks, evaluate, report
from scripts.profile_columns import profile_column, reconcile_counts, reconcile_sum
from scripts.scd_builder import OPEN_END, validate
from scripts.scd_loader import SCD_COLUMNS, plan_changes

TODAY = date(2026, 11, 19)


def source_row(well_id: int, purpose: str = "producer", formation_id: int = 7) -> dict:
    return {
        "well_id": well_id, "well_name": f"W-{well_id}", "field_id": 1,
        "field_name": "Field", "region": "North", "pad_id": 10, "pad_name": "Pad 10",
        "formation_id": formation_id, "formation_name": "ЮС2",
        "purpose": purpose, "trajectory": "horizontal",
        "spud_date": "2014-05-01", "start_date": "2015-01-01", "md_m": 3200.0,
    }


def current_row(well_id: int, purpose: str = "producer", formation_id: int = 7) -> dict:
    row = source_row(well_id, purpose, formation_id)
    row.update({"well_scd_id": 1, "valid_from": "2015-01-01",
                "valid_to": "9999-12-31", "is_current": True})
    return row


class TestPlanChanges:
    def test_new_well_gets_first_version(self):
        rows = plan_changes([], [source_row(1)], TODAY)
        assert len(rows) == 1
        assert rows[0]["valid_from"] == TODAY.isoformat()
        assert rows[0]["valid_to"] == OPEN_END.isoformat()
        assert rows[0]["is_current"] is True
        assert set(rows[0]) == set(SCD_COLUMNS)

    def test_unchanged_well_produces_nothing(self):
        assert plan_changes([current_row(1)], [source_row(1)], TODAY) == []

    def test_changed_purpose_closes_and_opens(self):
        rows = plan_changes([current_row(1)], [source_row(1, purpose="injector")], TODAY)
        assert len(rows) == 2
        closed, opened = rows
        assert closed["well_scd_id"] == 1              # та же версия, но закрытая
        assert closed["valid_to"] == TODAY.isoformat()
        assert closed["is_current"] is False
        assert opened["well_scd_id"] != closed["well_scd_id"]
        assert opened["valid_from"] == TODAY.isoformat()
        assert opened["purpose"] == "injector"
        assert opened["is_current"] is True

    def test_formation_change_counts_as_change(self):
        rows = plan_changes([current_row(1)], [source_row(1, formation_id=9)], TODAY)
        assert len(rows) == 2

    def test_mixed_source(self):
        current = [current_row(1), current_row(2)]
        source = [source_row(1), source_row(2, purpose="injector"), source_row(3)]
        rows = plan_changes(current, source, TODAY)
        # скважина 1 не изменилась → ничего; 2 → закрытие + новая; 3 → первая версия
        assert len(rows) == 3
        assert sum(1 for r in rows if r["is_current"]) == 2

    def test_second_change_same_day_updates_in_place(self):
        """Два изменения в один день не должны давать версию нулевой длины."""
        opened = current_row(1, purpose="producer")
        opened["valid_from"] = TODAY.isoformat()
        opened["well_scd_id"] = 777
        rows = plan_changes([opened], [source_row(1, purpose="injector")], TODAY)
        assert len(rows) == 1, "ожидаем обновление на месте, а не закрытие + открытие"
        row = rows[0]
        assert row["well_scd_id"] == 777
        assert row["valid_from"] == TODAY.isoformat()
        assert row["valid_to"] == OPEN_END.isoformat()
        assert row["is_current"] is True
        assert row["purpose"] == "injector"

    def test_plan_is_deterministic(self):
        first = plan_changes([current_row(1)], [source_row(1, purpose="injector")], TODAY)
        second = plan_changes([current_row(1)], [source_row(1, purpose="injector")], TODAY)
        assert [r["well_scd_id"] for r in first] == [r["well_scd_id"] for r in second]

    def test_planned_versions_pass_scd_invariants(self):
        rows = plan_changes([current_row(1)], [source_row(1, purpose="injector")], TODAY)
        from scripts.scd_builder import Version

        versions = [Version(well_id=int(r["well_id"]), attrs={"purpose": r["purpose"]},
                            valid_from=date.fromisoformat(r["valid_from"]),
                            valid_to=date.fromisoformat(r["valid_to"]),
                            is_current=bool(r["is_current"]),
                            well_scd_id=int(r["well_scd_id"])) for r in rows]
        assert validate(versions) == []


class TestQualityGate:
    def base(self, **overrides):
        kwargs = dict(column="oil_t", source_values=np.linspace(1, 100, 500),
                      target_values=np.linspace(1, 100, 500),
                      source_rows=500, target_rows=500,
                      source_sum=25_000.0, target_sum=25_000.0)
        kwargs.update(overrides)
        return build_checks(**kwargs)

    def test_clean_load_passes(self):
        verdict = self.base()
        assert verdict["passed"]
        assert "✓" in report(verdict)

    def test_row_loss_fails(self):
        verdict = self.base(target_rows=480, target_sum=24_000.0)
        assert not verdict["passed"]
        assert any("строк" in f for f in verdict["failures"])

    def test_duplicates_fail(self):
        verdict = self.base(target_rows=520, target_sum=26_000.0)
        assert not verdict["passed"]

    def test_value_substitution_fails(self):
        verdict = self.base(target_sum=25_010.0)     # 0,04 % — уже расхождение
        assert not verdict["passed"]
        assert any("сумма" in f for f in verdict["failures"])

    def test_trivial_distribution_shift_is_warning_not_failure(self):
        rng = np.random.default_rng(3)
        src = rng.normal(100, 15, 50_000)
        tgt = rng.normal(100.5, 15, 50_000)
        verdict = self.base(source_values=src, target_values=tgt)
        assert verdict["passed"]
        assert any("эффект мал" in w for w in verdict["warnings"])

    def test_material_distribution_shift_fails(self):
        rng = np.random.default_rng(3)
        src = rng.normal(100, 15, 20_000)
        tgt = np.concatenate([src[:18_000], np.zeros(2_000)])   # 10 % нулей
        verdict = self.base(source_values=src, target_values=tgt)
        assert not verdict["passed"]
