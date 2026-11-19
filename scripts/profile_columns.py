# -*- coding: utf-8 -*-
"""Профилировщик колонок: статистика распределения для ETL-контроля качества.

Считает для каждой колонки: null%, unique%, min/max, медиану, IQR, skewness,
и сравнивает распределения source vs target через KS-тест (Колмогоров-Смирнов).

Используется в Airflow DAG после загрузки месяца в ClickHouse.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats


@dataclass
class ColumnProfile:
    """Статистика одной колонки."""
    column: str
    dtype: str = ""
    count: int = 0
    null_count: int = 0
    null_pct: float = 0.0
    unique_count: int = 0
    unique_pct: float = 0.0

    # числовые метрики
    min_val: float | None = None
    max_val: float | None = None
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    q25: float | None = None
    q75: float | None = None
    iqr: float | None = None
    skewness: float | None = None
    kurtosis: float | None = None

    # результат KS-теста (source vs target)
    ks_stat: float | None = None
    ks_pvalue: float | None = None

    # флаги качества
    issues: list[str] = field(default_factory=list)


def profile_column(values: list | np.ndarray, column: str) -> ColumnProfile:
    """Посчитать статистику для одной колонки."""
    arr = np.asarray(values)
    p = ColumnProfile(column=column, count=len(arr), dtype=str(arr.dtype))
    p.null_count = int(np.sum(pd_isna(arr)))
    p.null_pct = round(p.null_count / p.count * 100, 2) if p.count > 0 else 0.0

    non_null = arr[~pd_isna(arr)]
    p.unique_count = len(np.unique(non_null))
    p.unique_pct = round(p.unique_count / p.count * 100, 2) if p.count > 0 else 0.0

    # числовая статистика
    numeric = pd_to_numeric_safe(non_null)
    if numeric is not None and len(numeric) > 0:
        p.min_val = float(np.min(numeric))
        p.max_val = float(np.max(numeric))
        p.mean = float(np.mean(numeric))
        p.median = float(np.median(numeric))
        p.std = float(np.std(numeric, ddof=1)) if len(numeric) > 1 else 0.0
        p.q25 = float(np.percentile(numeric, 25))
        p.q75 = float(np.percentile(numeric, 75))
        p.iqr = p.q75 - p.q25
        p.skewness = float(stats.skew(numeric)) if len(numeric) > 2 else 0.0
        p.kurtosis = float(stats.kurtosis(numeric)) if len(numeric) > 2 else 0.0

    # проверки качества
    _check_issues(p)
    return p


def compare_distributions(source: np.ndarray, target: np.ndarray,
                          column: str, alpha: float = 0.05) -> tuple[ColumnProfile, bool]:
    """KS-тест: совпадают ли распределения source и target.

    Возвращает (профиль target, passed). Если p > alpha — распределения
    статистически не различимы → загрузка корректна.
    """
    src = np.asarray(source, dtype=float)
    tgt = np.asarray(target, dtype=float)
    # убираем NaN
    src = src[~np.isnan(src)]
    tgt = tgt[~np.isnan(tgt)]

    if len(src) < 10 or len(tgt) < 10:
        return profile_column(target, column), True  # слишком мало данных для теста

    ks_stat, p_value = stats.ks_2samp(src, tgt)
    p = profile_column(target, column)
    p.ks_stat = round(ks_stat, 4)
    p.ks_pvalue = round(p_value, 6)
    passed = p_value > alpha
    if not passed:
        p.issues.append(f"KS-тест: распределение отличается (p={p_value:.4f} < {alpha})")
    return p, passed


def _check_issues(p: ColumnProfile) -> None:
    """Автоматические проверки качества."""
    if p.null_pct > 50:
        p.issues.append(f"Более 50% null ({p.null_pct}%)")
    if p.unique_count == 1 and p.count > 1:
        p.issues.append(f"Константа (единственное значение)")
    if p.skewness is not None and abs(p.skewness) > 3:
        p.issues.append(f"Сильная асимметрия (skew={p.skewness:.1f})")
    if p.iqr is not None and p.iqr == 0 and p.count > 10:
        p.issues.append("IQR = 0 (все значения в Q25-Q75 одинаковые)")


def pd_isna(arr):
    """Проверка NaN/None без зависимости от pandas."""
    if arr.dtype.kind in "fc":
        return np.isnan(arr)
    return np.isin(arr, [None]) | (arr == "")


def pd_to_numeric_safe(arr):
    """Попытка привести к float, если колонка числовая."""
    if arr.dtype.kind in "iuf":
        return arr.astype(float)
    try:
        return arr.astype(float)
    except (ValueError, TypeError):
        return None


def profile_report(profiles: list[ColumnProfile]) -> str:
    """Текстовый отчёт для логов Airflow."""
    lines = [f"{'Колонка':20s} {'Null%':>6s} {'Уник%':>6s} {'Медиана':>10s} {'IQR':>10s} {'Skew':>6s} {'Проблемы'}"]
    lines.append("-" * 100)
    for p in profiles:
        issues = "; ".join(p.issues) if p.issues else "✓"
        med = f"{p.median:.1f}" if p.median is not None else "-"
        iqr = f"{p.iqr:.1f}" if p.iqr is not None else "-"
        skew = f"{p.skewness:.1f}" if p.skewness is not None else "-"
        lines.append(f"{p.column:20s} {p.null_pct:5.1f}% {p.unique_pct:5.1f}% {med:>10s} {iqr:>10s} {skew:>6s} {issues}")
    return "\n".join(lines)
