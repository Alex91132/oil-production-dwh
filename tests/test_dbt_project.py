# -*- coding: utf-8 -*-
"""Целостность dbt-проекта и DAG — без запуска dbt и Airflow.

Эти тесты ловят ровно те ошибки, которые уже случались:
  * `target:` в dbt_project.yml (dbt 1.12 падает);
  * `tests:` вместо `data_tests:` (устаревший синтаксис);
  * `ref()` на несуществующую модель;
  * `source()` на незадекларированный источник;
  * возврат второго пути построения витрины (build_mart) в DAG.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DBT = ROOT / "dbt" / "oil_production"
DAG = ROOT / "airflow" / "dags" / "oil_dwh_monthly_load.py"

MODELS = {
    "stg_production_daily", "stg_injection_daily", "stg_dim_well",
    "mart_field_monthly", "mart_well_performance",
}
SOURCES = {"fact_production_daily", "fact_injection_daily", "dim_well", "dim_well_scd"}


def model_files() -> dict[str, Path]:
    return {path.stem: path for path in (DBT / "models").rglob("*.sql")}


def all_model_sql() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (DBT / "models").rglob("*.sql"))


def project() -> dict:
    return yaml.safe_load((DBT / "dbt_project.yml").read_text(encoding="utf-8"))


def schema() -> dict:
    return yaml.safe_load((DBT / "models" / "schema.yml").read_text(encoding="utf-8"))


def test_project_has_no_target_key():
    """dbt 1.12: `target` в dbt_project.yml — фатальная ошибка, а не подсказка."""
    assert "target" not in project()


def test_all_models_present():
    assert set(model_files()) == MODELS


def test_every_ref_points_to_existing_model():
    refs = set(re.findall(r"ref\('(\w+)'\)", all_model_sql()))
    assert refs, "в моделях нет ни одного ref — подозрительно"
    missing = refs - MODELS
    assert not missing, f"ref на несуществующие модели: {sorted(missing)}"


def test_every_source_is_declared():
    used = set(re.findall(r"source\('dwh',\s*'(\w+)'\)", all_model_sql()))
    declared = {table["name"] for source in schema()["sources"] for table in source["tables"]}
    assert used == SOURCES
    assert used <= declared, f"источники без объявления: {sorted(used - declared)}"


def test_generic_tests_use_data_tests_key():
    text = (DBT / "models" / "schema.yml").read_text(encoding="utf-8")
    assert "data_tests:" in text
    assert not re.search(r"^\s+tests:", text, flags=re.MULTILINE), \
        "в schema.yml остался устаревший ключ tests: — нужен data_tests:"


def test_each_model_has_tests():
    described = {model["name"] for model in schema()["models"]}
    assert described == MODELS
    for model in schema()["models"]:
        columns = model.get("columns") or []
        assert columns, f"у модели {model['name']} нет описания колонок с тестами"


def test_custom_tests_reference_existing_models():
    tests_dir = DBT / "tests"
    files = sorted(path.name for path in tests_dir.glob("*.sql"))
    expected = {
        "assert_oil_non_negative.sql",
        "assert_watercut_bounds.sql",
        "assert_well_exists_in_dim.sql",
        "assert_mart_matches_facts.sql",
        "assert_mart_grain_unique.sql",
        "assert_watercut_null_only_without_liquid.sql",
        "assert_injection_not_lost.sql",
    }
    assert set(files) == expected
    for path in tests_dir.glob("*.sql"):
        for ref in re.findall(r"ref\('(\w+)'\)", path.read_text(encoding="utf-8")):
            assert ref in MODELS, f"{path.name}: ref на несуществующую модель {ref}"


def test_ci_seed_covers_all_sources():
    seed = (ROOT / "dbt" / "ci_seed.sql").read_text(encoding="utf-8")
    for table in SOURCES:
        assert f"dwh.{table}" in seed, f"в ci_seed нет {table}"


def dag_source() -> str:
    return DAG.read_text(encoding="utf-8")


def dag_task_names() -> set[str]:
    """Имена задач, объявленных декоратором @task внутри DAG."""
    tree = ast.parse(dag_source())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "task":
                    names.add(node.name)
    return names


def test_dag_uses_dbt_and_has_no_manual_mart():
    source = dag_source()
    tasks = dag_task_names()
    assert "dbt_build" in tasks, "в DAG нет задачи dbt_build"
    assert "build_mart" not in tasks, "вернулся ручной build_mart — два источника правды"
    assert "MART_SQL" not in source, "остался ручной SQL витрины"


def test_reconcile_checks_dbt_mart():
    source = dag_source()
    assert "dwh_marts.mart_field_monthly" in source, "сверка не смотрит в витрину dbt"


def test_dag_file_parses():
    ast.parse(dag_source())
