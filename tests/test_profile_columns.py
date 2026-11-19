# -*- coding: utf-8 -*-
"""Тесты профилировщика колонок и SCD-логики."""
import numpy as np
import pytest

from scripts.profile_columns import (
    ColumnProfile, compare_distributions, profile_column, profile_report,
    reconcile_counts, reconcile_report, reconcile_sum,
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

    def test_too_few_data_passes_but_is_flagged(self):
        src = np.array([1.0, 2.0])
        tgt = np.array([3.0, 4.0])
        profile, passed = compare_distributions(src, tgt, "test")
        assert passed  # слишком мало данных — не валим загрузку
        assert any("мало данных" in issue for issue in profile.issues), \
            "молчаливый пропуск контроля недопустим — должно быть предупреждение"

    def test_trivial_shift_on_big_data_does_not_fail(self):
        """На больших n p-value падает от любого сдвига — решает сила эффекта."""
        rng = np.random.default_rng(7)
        src = rng.normal(100, 15, 200_000)
        tgt = rng.normal(100.5, 15, 200_000)          # сдвиг 0,5 % от среднего
        profile, passed = compare_distributions(src, tgt, "oil")
        assert passed
        assert profile.ks_pvalue < 0.05               # KS «значим»
        assert any("эффект мал" in issue for issue in profile.issues)

    def test_real_corruption_fails(self):
        rng = np.random.default_rng(7)
        src = rng.normal(100, 15, 50_000)
        tgt = src.copy()
        tgt[: int(len(tgt) * 0.05)] = 0.0             # 5 % строк обнулили
        _, passed = compare_distributions(src, tgt, "oil")
        assert not passed


class TestReconciliation:
    """То, чего KS не умеет: потерю строк, дубликаты и подмену значений."""

    def test_counts_ok(self):
        check = reconcile_counts(1000, 1000)
        assert check["passed"] and check["diff"] == 0

    def test_counts_catch_lost_rows(self):
        check = reconcile_counts(200_000, 190_000)
        assert not check["passed"]
        assert "разница -10,000" in check["message"]

    def test_counts_catch_duplicates(self):
        check = reconcile_counts(200_000, 220_000)
        assert not check["passed"]

    def test_sum_ok_within_tolerance(self):
        assert reconcile_sum("oil_t", 1_234_567.89, 1_234_567.89)["passed"]

    def test_sum_catches_substitution(self):
        check = reconcile_sum("oil_t", 1000.0, 1001.0)
        assert not check["passed"]
        assert "0.1000 %" in check["message"]

    def test_report_marks_failures(self):
        report = reconcile_report([reconcile_counts(10, 9), reconcile_sum("oil", 5.0, 5.0)])
        assert "✗" in report and "✓" in report


class TestProfileReport:
    def test_report_renders(self):
        p1 = profile_column([1, 2, 3, 4, 5], "col_a")
        p2 = profile_column([1, 1, 1, 1, 1], "col_b")  # константа
        report = profile_report([p1, p2])
        assert "col_a" in report
        assert "col_b" in report
        assert "Константа" in report
