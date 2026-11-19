# -*- coding: utf-8 -*-
"""Тесты профилировщика колонок и SCD-логики."""
import numpy as np
import pytest

from scripts.profile_columns import (
    ColumnProfile, compare_distributions, profile_column, profile_report,
)


class TestProfileColumn:
    def test_basic_stats(self):
        vals = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        p = profile_column(vals, "test")
        assert p.count == 10
        assert p.null_pct == 0.0
        assert p.median == 5.5
        assert p.iqr == 4.5  # Q75(7.75) - Q25(3.25)
        assert p.min_val == 1
        assert p.max_val == 10

    def test_null_percentage(self):
        vals = [1, None, 3, None, 5, 6, 7, 8, 9, 10]
        arr = np.array([1, np.nan, 3, np.nan, 5, 6, 7, 8, 9, 10], dtype=float)
        p = profile_column(arr, "with_nulls")
        assert p.null_pct == 20.0

    def test_constant_column_flagged(self):
        vals = [5, 5, 5, 5, 5, 5, 5, 5]
        p = profile_column(vals, "constant")
        assert "Константа" in "; ".join(p.issues)

    def test_skewed_column_flagged(self):
        vals = np.concatenate([np.random.exponential(1, 500), [100]])
        p = profile_column(vals, "skewed")
        assert p.skewness is not None
        # exponential + outlier → сильная асимметрия
        assert abs(p.skewness) > 1 or "асимметрия" in "; ".join(p.issues)

    def test_string_column(self):
        vals = np.array(["a", "b", "c", "a", "b"])
        p = profile_column(vals, "strings")
        assert p.unique_count == 3
        assert p.median is None  # не числовая


class TestCompareDistributions:
    def test_same_distribution_passes(self):
        rng = np.random.default_rng(42)
        src = rng.normal(100, 15, 1000)
        tgt = rng.normal(100, 15, 1000)
        _, passed = compare_distributions(src, tgt, "test")
        assert passed  # из одного распределения → p > 0.05

    def test_different_distribution_fails(self):
        rng = np.random.default_rng(42)
        src = rng.normal(100, 15, 1000)
        tgt = rng.normal(120, 15, 1000)  # сдвиг среднего
        _, passed = compare_distributions(src, tgt, "test")
        assert not passed  # разные распределения → p < 0.05

    def test_too_few_data_passes(self):
        src = np.array([1.0, 2.0])
        tgt = np.array([3.0, 4.0])
        _, passed = compare_distributions(src, tgt, "test")
        assert passed  # слишком мало данных — пропускаем


class TestProfileReport:
    def test_report_renders(self):
        p1 = profile_column([1, 2, 3, 4, 5], "col_a")
        p2 = profile_column([1, 1, 1, 1, 1], "col_b")  # константа
        report = profile_report([p1, p2])
        assert "col_a" in report
        assert "col_b" in report
        assert "Константа" in report
