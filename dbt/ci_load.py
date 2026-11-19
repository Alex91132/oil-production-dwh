# -*- coding: utf-8 -*-
"""Загружает ci_seed.sql в ClickHouse по одному оператору.

HTTP-интерфейс ClickHouse не принимает несколько операторов в одном запросе
(`Multi-statements are not allowed`), поэтому режем файл по `;` и отправляем
каждый оператор отдельно.

    python dbt/ci_load.py            # по умолчанию localhost:8123, dwh/dwh
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

import clickhouse_connect

HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
PORT = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
USER = os.environ.get("CLICKHOUSE_USER", "dwh")
PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "dwh")

SEED = pathlib.Path(__file__).with_name("ci_seed.sql")


def statements(sql: str) -> list[str]:
    """Режет файл на операторы, отбрасывая комментарии и пустые строки."""
    cleaned = []
    for chunk in sql.split(";"):
        lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if statement:
            cleaned.append(statement)
    return cleaned


def main() -> int:
    client = None
    for attempt in range(1, 31):
        try:
            client = clickhouse_connect.get_client(host=HOST, port=PORT,
                                                   username=USER, password=PASSWORD)
            break
        except Exception as exc:                       # noqa: BLE001 — ждём готовности
            print(f"попытка {attempt}: {type(exc).__name__}: {exc}")
            time.sleep(3)
    if client is None:
        print("ClickHouse недоступен", file=sys.stderr)
        return 1

    for statement in statements(SEED.read_text(encoding="utf-8")):
        client.command(statement)

    production = client.query("SELECT count() FROM dwh.fact_production_daily").result_rows[0][0]
    print(f"seed загружен: fact_production_daily = {production} строк")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
