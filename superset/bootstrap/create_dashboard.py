"""
«Дашборд как код»: создаёт в Superset подключение к ClickHouse, датасеты с метриками,
графики и дашборд через REST API.

Скрипт идемпотентен: при повторном запуске пересоздаёт дашборд, графики и датасеты
с теми же именами, поэтому любое изменение дашборда делается правкой этого файла.

Переменные окружения: SUPERSET_URL, SUPERSET_ADMIN_USER, SUPERSET_ADMIN_PASSWORD,
CLICKHOUSE_URI.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")
CH_URI = os.environ.get("CLICKHOUSE_URI", "clickhousedb://dwh:dwh@clickhouse:8123/dwh")
SQL_DIR = Path(os.environ.get("SQL_DIR", Path(__file__).parent / "sql"))

DATABASE_NAME = "ClickHouse DWH"
DASHBOARD_SLUG = "oil-production"
DASHBOARD_TITLE = "Нефтедобыча: обзор месторождений"
FIELD_COLORS = {"Кедровое": "#1f77b4", "Озёрное": "#2ca02c", "Таёжное": "#ff7f0e"}


# ---------------------------------------------------------------------------
# Клиент REST API
# ---------------------------------------------------------------------------

class Superset:
    def __init__(self):
        self.s = requests.Session()
        token = self._call("POST", "/api/v1/security/login", json={
            "username": USER, "password": PASSWORD, "provider": "db", "refresh": True})["access_token"]
        self.s.headers["Authorization"] = f"Bearer {token}"
        csrf = self._call("GET", "/api/v1/security/csrf_token/")["result"]
        self.s.headers.update({"X-CSRFToken": csrf, "Referer": BASE})

    def _call(self, method, path, **kwargs):
        r = self.s.request(method, BASE + path, timeout=60, **kwargs)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    get = lambda self, path: self._call("GET", path)
    post = lambda self, path, body: self._call("POST", path, json=body)
    put = lambda self, path, body: self._call("PUT", path, json=body)
    delete = lambda self, path: self._call("DELETE", path)

    def list(self, resource):
        return self.get(f"/api/v1/{resource}/?q=(page:0,page_size:1000)")["result"]


def wait_for_superset():
    for _ in range(60):
        try:
            if requests.get(f"{BASE}/health", timeout=5).ok:
                return
        except requests.ConnectionError:
            pass
        time.sleep(5)
    sys.exit("Superset недоступен")


def virtual_sql(filename):
    """SQL виртуального датасета из sql/clickhouse: без комментариев и финальной «;»."""
    text = (SQL_DIR / filename).read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("--")]
    return re.sub(r";\s*$", "", "\n".join(lines).strip())


# ---------------------------------------------------------------------------
# Описание датасетов и графиков
# ---------------------------------------------------------------------------

DATASETS = {
    "mart": {
        "table_name": "mart_field_monthly",
        "main_dttm_col": "month",
        "verbose": {"month": "Месяц", "field_name": "Месторождение"},
        "metrics": [
            ("oil_t_d", "SUM(oil_t_per_day)", "Добыча нефти, т/сут", ",.0f"),
            ("oil_kt", "SUM(oil_t) / 1000", "Добыча нефти, тыс. т", ",.1f"),
            ("producing_wells", "SUM(producing_wells)", "Действующий добывающий фонд", ",.0f"),
            ("watercut", "sum(toFloat64(water_m3)) / sum(liquid_m3)", "Обводнённость", ".1%"),
            ("compensation", "sum(toFloat64(injection_m3)) / sum(liquid_m3)", "Компенсация отборов", ".0%"),
        ],
    },
    "interventions": {
        "table_name": "v_interventions",
        "sql": """
            SELECT i.intervention_id, i.type_name, i.category, i.start_date, i.end_date,
                   i.duration_days, toFloat64(i.cost_mln_rub) AS cost_mln_rub,
                   w.field_name, w.well_name
            FROM dwh.fact_interventions AS i
            INNER JOIN dwh.dim_well AS w ON w.well_id = i.well_id""",
        "main_dttm_col": "start_date",
        "verbose": {"type_name": "Вид ГТМ", "start_date": "Дата начала", "field_name": "Месторождение"},
        "metrics": [
            ("count_interventions", "COUNT(*)", "Количество ГТМ", ",.0f"),
            ("cost", "SUM(cost_mln_rub)", "Затраты, млн ₽", ",.1f"),
        ],
    },
    "effect": {
        "table_name": "v_intervention_effect",
        "sql_file": "02_intervention_decay_asof.sql",
        "verbose": {"intervention": "Вид ГТМ", "n": "Мероприятий", "month_1": "1-й месяц",
                    "month_3": "3-й месяц", "month_6": "6-й месяц", "month_12": "12-й месяц"},
        "metrics": [],
    },
}


def ts_params(metric, y_format, groupby=("field_name",), **extra):
    """Параметры линейного графика по месяцам."""
    return {
        "viz_type": "echarts_timeseries_line",
        "x_axis": "month", "time_grain_sqla": "P1M", "time_range": "No filter",
        "metrics": [metric], "groupby": list(groupby), "adhoc_filters": [],
        "row_limit": 10000, "truncate_metric": True, "rich_tooltip": True,
        "show_legend": True, "legendType": "plain", "legendOrientation": "top",
        "x_axis_time_format": "%Y", "tooltipTimeFormat": "%B %Y", "y_axis_format": y_format,
        "markerEnabled": False, "zoomable": False, "seriesType": "line", **extra,
    }


def kpi_params(metric, y_format, compare=True):
    """Крупное число за последний месяц + тренд (+ сравнение с прошлым годом)."""
    params = {
        "viz_type": "big_number",
        "x_axis": "month", "time_grain_sqla": "P1M", "time_range": "No filter",
        "metric": metric, "adhoc_filters": [],
        "show_trend_line": True, "start_y_axis_at_zero": False,
        "y_axis_format": y_format, "header_font_size": 0.4, "subheader_font_size": 0.15,
    }
    if compare:
        params |= {"compare_lag": 12, "compare_suffix": "к прошлому году"}
    return params


CHARTS = [
    # ключ, название, датасет, параметры
    ("kpi_oil", "Добыча нефти, т/сут", "mart", kpi_params("oil_t_d", ",.0f")),
    ("kpi_wells", "Действующий добывающий фонд", "mart", kpi_params("producing_wells", ",.0f")),
    # Без сравнения: для доли Superset показал бы относительное изменение
    # («+14,5 %»), которое легко принять за процентные пункты (на деле +6,4 п.п.)
    ("kpi_wc", "Обводнённость", "mart", kpi_params("watercut", ".1%", compare=False)),
    ("oil_by_field", "Среднесуточная добыча нефти по месторождениям, т/сут", "mart",
     ts_params("oil_t_d", ",.0f")),
    ("compensation", "Компенсация отборов закачкой", "mart", ts_params("compensation", ".0%")),
    ("watercut_by_field", "Обводнённость по месторождениям", "mart", ts_params("watercut", ".0%")),
    ("interventions_by_year", "ГТМ по видам и годам", "interventions", {
        "viz_type": "echarts_timeseries_bar",
        "x_axis": "start_date", "time_grain_sqla": "P1Y", "time_range": "No filter",
        "metrics": ["count_interventions"], "groupby": ["type_name"], "adhoc_filters": [],
        "row_limit": 10000, "stack": "Stack", "show_legend": True, "legendType": "plain",
        "legendOrientation": "top", "x_axis_time_format": "%Y", "y_axis_format": ",.0f",
        "rich_tooltip": True, "truncate_metric": True,
    }),
    ("effect_table", "Эффект ГТМ: медиана дебита относительно исходного (×)", "effect", {
        "viz_type": "table", "query_mode": "raw",
        "all_columns": ["intervention", "n", "month_1", "month_3", "month_6", "month_12"],
        "order_by_cols": [], "row_limit": 100, "server_pagination": False,
        "include_search": False, "show_cell_bars": True, "adhoc_filters": [],
        "table_timestamp_format": "smart_date",
    }),
]

INTRO = """\
### Нефтедобыча: обзор трёх месторождений (синтетические данные)

Данные идут по цепочке **PostgreSQL → Airflow → ClickHouse**: витрина `mart_field_monthly`
пересобирается ежемесячно и сверяется с источником до последнего знака.
Фильтры слева — по месторождению и периоду.
[Код проекта на GitHub](https://github.com/Alex91132/oil-production-dwh)
"""

LAYOUT = [  # строки дашборда: (ключ графика или "intro", ширина из 12, высота)
    [("intro", 12, 16)],
    [("kpi_oil", 4, 40), ("kpi_wells", 4, 40), ("kpi_wc", 4, 40)],
    [("oil_by_field", 6, 55), ("compensation", 6, 55)],
    [("watercut_by_field", 6, 55), ("interventions_by_year", 6, 55)],
    [("effect_table", 12, 38)],
]


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------

def ensure_database(api):
    for db in api.list("database"):
        if db["database_name"] == DATABASE_NAME:
            api.put(f"/api/v1/database/{db['id']}", {"sqlalchemy_uri": CH_URI})
            return db["id"]
    return api.post("/api/v1/database/", {
        "database_name": DATABASE_NAME, "sqlalchemy_uri": CH_URI, "expose_in_sqllab": True})["id"]


def remove_previous(api):
    """Удалить дашборд, графики и датасеты прошлого запуска (по именам)."""
    for d in api.list("dashboard"):
        if d.get("slug") == DASHBOARD_SLUG:
            api.delete(f"/api/v1/dashboard/{d['id']}")
    names = {title for _, title, _, _ in CHARTS}
    for c in api.list("chart"):
        if c["slice_name"] in names:
            api.delete(f"/api/v1/chart/{c['id']}")
    tables = {d["table_name"] for d in DATASETS.values()}
    for d in api.list("dataset"):
        if d["table_name"] in tables:
            api.delete(f"/api/v1/dataset/{d['id']}")


def create_dataset(api, db_id, spec):
    body = {"database": db_id, "schema": "dwh", "table_name": spec["table_name"]}
    sql = spec.get("sql") or (virtual_sql(spec["sql_file"]) if "sql_file" in spec else None)
    if sql:
        body["sql"] = sql.strip()
    ds_id = api.post("/api/v1/dataset/", body)["id"]
    if sql:
        api.put(f"/api/v1/dataset/{ds_id}/refresh", {})          # подтянуть колонки запроса
    current = api.get(f"/api/v1/dataset/{ds_id}")["result"]
    columns = [{k: c[k] for k in ("id", "column_name", "type", "is_dttm", "groupby", "filterable")}
               | {"verbose_name": spec["verbose"].get(c["column_name"], c.get("verbose_name"))}
               for c in current["columns"]]
    update = {"columns": columns,
              "metrics": [{"metric_name": n, "expression": e, "verbose_name": v, "d3format": f}
                          for n, e, v, f in spec["metrics"]]}
    if spec.get("main_dttm_col"):
        update["main_dttm_col"] = spec["main_dttm_col"]
    api.put(f"/api/v1/dataset/{ds_id}", update)
    return ds_id


def build_layout(chart_ids, titles):
    pos = {"DASHBOARD_VERSION_KEY": "v2",
           "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
           "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}}}
    for r, row in enumerate(LAYOUT, 1):
        row_id = f"ROW-{r}"
        pos["GRID_ID"]["children"].append(row_id)
        pos[row_id] = {"type": "ROW", "id": row_id, "children": [],
                       "parents": ["ROOT_ID", "GRID_ID"],
                       "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for key, width, height in row:
            parents = ["ROOT_ID", "GRID_ID", row_id]
            if key == "intro":
                item_id = "MARKDOWN-intro"
                pos[item_id] = {"type": "MARKDOWN", "id": item_id, "children": [], "parents": parents,
                                "meta": {"width": width, "height": height, "code": INTRO}}
            else:
                item_id = f"CHART-{key}"
                pos[item_id] = {"type": "CHART", "id": item_id, "children": [], "parents": parents,
                                "meta": {"width": width, "height": height,
                                         "chartId": chart_ids[key], "sliceName": titles[key]}}
            pos[row_id]["children"].append(item_id)
    return pos


def native_filters(mart_id, chart_ids):
    in_scope = [cid for key, cid in chart_ids.items() if key != "effect_table"]
    common = {"cascadeParentIds": [], "type": "NATIVE_FILTER", "description": "",
              "defaultDataMask": {"extraFormData": {}, "filterState": {}, "ownState": {}},
              # таблица эффекта ГТМ — агрегат по всей истории, фильтры к ней не применяются
              "scope": {"rootPath": ["ROOT_ID"], "excluded": [chart_ids["effect_table"]]},
              "chartsInScope": in_scope, "tabsInScope": []}
    return [
        {"id": "NATIVE_FILTER-field", "name": "Месторождение", "filterType": "filter_select",
         "targets": [{"datasetId": mart_id, "column": {"name": "field_name"}}],
         "controlValues": {"multiSelect": True, "enableEmptyFilter": False, "defaultToFirstItem": False,
                           "searchAllOptions": False, "inverseSelection": False},
         **common},
        {"id": "NATIVE_FILTER-period", "name": "Период", "filterType": "filter_time",
         "targets": [{}], "controlValues": {}, **common},
    ]


def main():
    wait_for_superset()
    api = Superset()
    db_id = ensure_database(api)
    remove_previous(api)

    ds_ids = {key: create_dataset(api, db_id, spec) for key, spec in DATASETS.items()}
    print("Датасеты:", ds_ids)

    dash_id = api.post("/api/v1/dashboard/", {
        "dashboard_title": DASHBOARD_TITLE, "slug": DASHBOARD_SLUG, "published": True})["id"]

    chart_ids, titles = {}, {}
    for key, title, ds_key, params in CHARTS:
        params = {**params, "datasource": f"{ds_ids[ds_key]}__table"}
        chart_ids[key] = api.post("/api/v1/chart/", {
            "slice_name": title, "viz_type": params["viz_type"],
            "datasource_id": ds_ids[ds_key], "datasource_type": "table",
            "params": json.dumps(params, ensure_ascii=False), "dashboards": [dash_id]})["id"]
        titles[key] = title
    print("Графики:", chart_ids)

    metadata = {
        "native_filter_configuration": native_filters(ds_ids["mart"], chart_ids),
        "label_colors": FIELD_COLORS, "shared_label_colors": {}, "color_scheme": "",
        "cross_filters_enabled": True, "refresh_frequency": 0, "expanded_slices": {},
        "timed_refresh_immune_slices": [], "default_filters": "{}",
        "chart_configuration": {},
        "global_chart_configuration": {"scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                                       "chartsInScope": list(chart_ids.values())},
    }
    api.put(f"/api/v1/dashboard/{dash_id}", {
        "position_json": json.dumps(build_layout(chart_ids, titles), ensure_ascii=False),
        "json_metadata": json.dumps(metadata, ensure_ascii=False)})

    print(f"Готово: {BASE}/superset/dashboard/{DASHBOARD_SLUG}/")


if __name__ == "__main__":
    main()
