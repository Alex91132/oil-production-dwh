"""
Прогоняет все аналитические запросы и сохраняет результаты в Markdown —
чтобы их можно было посмотреть прямо на GitHub:
  * sql/analytics, sql/checks (PostgreSQL) → docs/analytics_results.md
  * sql/clickhouse (хранилище)              → docs/analytics_results_clickhouse.md

Запуск (стенд должен быть поднят через docker compose):
    python scripts/run_analytics.py
"""

import base64
import json
import os
import re
import time
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
MAX_ROWS = 25


def fmt(value):
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(fmt(v) for v in value) + "]"
    return str(value)


def clickhouse_query(sql):
    """Запрос к ClickHouse через HTTP-интерфейс; возвращает (колонки, строки)."""
    url = (f"http://{os.getenv('CH_HOST', 'localhost')}:{os.getenv('CH_HTTP_PORT', '8123')}/"
           "?database=dwh&default_format=JSONCompact")
    auth = base64.b64encode(f"{os.getenv('CH_USER', 'dwh')}:{os.getenv('CH_PASSWORD', 'dwh')}".encode())
    req = urllib.request.Request(url, data=sql.encode("utf-8"),
                                 headers={"Authorization": "Basic " + auth.decode()})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read())
    return [m["name"] for m in payload["meta"]], payload["data"]


def question(sql_text):
    """Первый комментарий «-- Вопрос: ...» (может занимать несколько строк)."""
    lines, grabbing = [], False
    for line in sql_text.splitlines():
        if line.startswith("-- Вопрос:"):
            grabbing = True
            lines.append(line.removeprefix("-- Вопрос:").strip())
        elif grabbing and line.startswith("--") and not line.startswith("-- Техники"):
            lines.append(line.removeprefix("--").strip())
        elif grabbing:
            break
    return " ".join(lines)


def to_markdown(columns, rows):
    out = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows[:MAX_ROWS]:
        out.append("| " + " | ".join(fmt(v) for v in row) + " |")
    if len(rows) > MAX_ROWS:
        out.append(f"\n_…показаны первые {MAX_ROWS} из {len(rows)} строк_")
    return "\n".join(out)


def main():
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"), port=int(os.getenv("PGPORT", "5435")),
        user=os.getenv("PGUSER", "dwh"), password=os.getenv("PGPASSWORD", "dwh"),
        dbname=os.getenv("PGDATABASE", "oilfield"))
    cur = conn.cursor()

    report = ["# Результаты аналитических запросов",
              "",
              "Сгенерировано скриптом `scripts/run_analytics.py` на синтетических данных (seed 42).",
              ""]
    for folder in ("analytics", "checks"):
        for path in sorted((ROOT / "sql" / folder).glob("*.sql")):
            sql_text = path.read_text(encoding="utf-8")
            t0 = time.perf_counter()
            cur.execute(sql_text)
            ms = (time.perf_counter() - t0) * 1000
            rows = cur.fetchall()
            columns = [d.name for d in cur.description]
            title = re.sub(r"^\d+_", "", path.stem).replace("_", " ")
            report += [f"## `{folder}/{path.name}` — {title}", ""]
            if q := question(sql_text):
                report += [f"**Вопрос:** {q}", ""]
            report += [to_markdown(columns, rows), "", f"_Время выполнения: {ms:.0f} мс_", ""]
            print(f"{folder}/{path.name}: {len(rows)} строк, {ms:.0f} мс")

    out = ROOT / "docs" / "analytics_results.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"Сохранено: {out.relative_to(ROOT)}")

    # --- ClickHouse
    report = ["# Результаты запросов к хранилищу ClickHouse",
              "",
              "Сгенерировано скриптом `scripts/run_analytics.py` после загрузки хранилища DAG-ом Airflow.",
              ""]
    for path in sorted((ROOT / "sql" / "clickhouse").glob("*.sql")):
        sql_text = path.read_text(encoding="utf-8")
        t0 = time.perf_counter()
        columns, rows = clickhouse_query(sql_text)
        ms = (time.perf_counter() - t0) * 1000
        title = re.sub(r"^\d+_", "", path.stem).replace("_", " ")
        report += [f"## `clickhouse/{path.name}` — {title}", ""]
        if q := question(sql_text):
            report += [f"**Вопрос:** {q}", ""]
        report += [to_markdown(columns, rows), "", f"_Время выполнения: {ms:.0f} мс_", ""]
        print(f"clickhouse/{path.name}: {len(rows)} строк, {ms:.0f} мс")

    out = ROOT / "docs" / "analytics_results_clickhouse.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"Сохранено: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
