"""
Прогоняет все запросы из sql/analytics и sql/checks и сохраняет результаты
в docs/analytics_results.md — чтобы их можно было посмотреть прямо на GitHub.

Запуск (БД должна быть поднята через docker compose):
    python scripts/run_analytics.py
"""

import os
import re
import time
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
    return str(value)


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


if __name__ == "__main__":
    main()
