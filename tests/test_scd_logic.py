# -*- coding: utf-8 -*-
"""Тесты логики SCD Type 2 (без ClickHouse — проверяем инварианты версий)."""
import numpy as np
import pytest

from scripts.profile_columns import profile_column


class TestSCDInvariants:
    """Проверяем инварианты SCD Type 2 на данных (эмуляция без БД)."""

    def setup_method(self):
        """Эмуляция таблицы dim_well_scd: две версии скважины (перевод под закачку)."""
        self.versions = [
            {"well_id": 1, "purpose": "producer", "valid_from": "2015-01-01", "valid_to": "2018-06-01", "is_current": False},
            {"well_id": 1, "purpose": "injector",  "valid_from": "2018-06-01", "valid_to": "9999-12-31", "is_current": True},
            {"well_id": 2, "purpose": "producer", "valid_from": "2016-03-01", "valid_to": "9999-12-31", "is_current": True},
        ]

    def test_one_current_per_well(self):
        """Инвариант: у каждого well_id ровно одна is_current=True версия."""
        by_well = {}
        for v in self.versions:
            by_well.setdefault(v["well_id"], []).append(v)
        for well_id, versions in by_well.items():
            current_count = sum(1 for v in versions if v["is_current"])
            assert current_count == 1, f"well_id={well_id}: {current_count} текущих версий (должна быть 1)"

    def test_no_overlapping_periods(self):
        """Инвариант: версии одного well_id не пересекаются по времени."""
        by_well = {}
        for v in self.versions:
            by_well.setdefault(v["well_id"], []).append(v)
        for well_id, versions in by_well.items():
            sorted_v = sorted(versions, key=lambda x: x["valid_from"])
            for i in range(len(sorted_v) - 1):
                assert sorted_v[i]["valid_to"] <= sorted_v[i + 1]["valid_from"], \
                    f"well_id={well_id}: пересечение {sorted_v[i]['valid_to']} > {sorted_v[i+1]['valid_from']}"

    def test_point_in_time_lookup(self):
        """AS OF запрос: на дату 2017-01-01 скважина 1 — producer."""
        as_of = "2017-01-01"
        match = [v for v in self.versions
                 if v["well_id"] == 1 and v["valid_from"] <= as_of < v["valid_to"]]
        assert len(match) == 1
        assert match[0]["purpose"] == "producer"

    def test_after_conversion(self):
        """AS OF запрос: после 2018-06-01 скважина 1 — injector."""
        as_of = "2019-01-01"
        match = [v for v in self.versions
                 if v["well_id"] == 1 and v["valid_from"] <= as_of < v["valid_to"]]
        assert len(match) == 1
        assert match[0]["purpose"] == "injector"
