# -*- coding: utf-8 -*-
"""Контроль качества после загрузки: сверки + профили колонок в одном вердикте.

Порядок важен: сначала количественные проверки (строки, суммы) — они ловят потерю
и подмену данных; потом уже профили с KS, которые отвечают за форму распределения.
"""

from __future__ import annotations

from scripts.profile_columns import (
    ColumnProfile, compare_distributions, reconcile_counts, reconcile_sum,
)


def evaluate(counts: dict, sums: list[dict], profiles: list[ColumnProfile]) -> dict:
    """Собирает вердикт: что провалилось, что предупреждение.

    `counts` — результат reconcile_counts, `sums` — список reconcile_sum,
    `profiles` — профили колонок после сравнения распределений.
    """
    failures: list[str] = []
    warnings: list[str] = []

    if not counts["passed"]:
        failures.append(counts["message"])
    for check in sums:
        if not check["passed"]:
            failures.append(check["message"])

    for profile in profiles:
        for issue in profile.issues:
            text = f"{profile.column}: {issue}"
            if issue.startswith("KS-тест"):
                failures.append(text)          # материальное расхождение распределения
            else:
                warnings.append(text)          # null%, константа, малый эффект и т.п.

    return {"passed": not failures, "failures": failures, "warnings": warnings}


def build_checks(column: str, source_values, target_values,
                 source_rows: int, target_rows: int,
                 source_sum: float, target_sum: float) -> dict:
    """Полный набор проверок для одной метрики: строки, сумма, распределение."""
    profile, _ = compare_distributions(source_values, target_values, column)
    counts = reconcile_counts(source_rows, target_rows)
    sums = [reconcile_sum(column, source_sum, target_sum)]
    verdict = evaluate(counts, sums, [profile])
    verdict["profile"] = profile
    return verdict


def report(verdict: dict) -> str:
    """Текст для лога Airflow."""
    lines = ["контроль качества после загрузки"]
    if verdict["passed"]:
        lines.append("  ✓ количественные сверки и распределения в порядке")
    for failure in verdict["failures"]:
        lines.append(f"  ✗ {failure}")
    for warning in verdict["warnings"]:
        lines.append(f"  ! {warning}")
    return "\n".join(lines)
