#!/bin/sh
# Ждём, пока Airflow загрузит факты, и только потом собираем модели.
# Без ожидания `dbt build` падает на пустых источниках при первом `docker compose up`.
set -eu

echo "dbt: ждём данные в ClickHouse (до 10 минут)…"

python - <<'PY'
import os
import sys
import time

import clickhouse_connect

host = os.environ.get("CLICKHOUSE_HOST", "clickhouse")
port = int(os.environ.get("CLICKHOUSE_PORT", "8123"))
user = os.environ.get("CLICKHOUSE_USER", "default")
password = os.environ.get("CLICKHOUSE_PASSWORD", "")
database = os.environ.get("CLICKHOUSE_DB", "dwh")

for attempt in range(1, 61):
    try:
        client = clickhouse_connect.get_client(
            host=host, port=port, username=user, password=password, database=database
        )
        rows = client.query(f"SELECT count() FROM {database}.fact_production_daily").result_rows[0][0]
        if rows > 0:
            print(f"dbt: данные есть — {rows} строк в fact_production_daily")
            sys.exit(0)
        print(f"dbt: попытка {attempt}: таблица есть, данных нет")
    except Exception as exc:                       # noqa: BLE001 — ждём любую готовность
        print(f"dbt: попытка {attempt}: {type(exc).__name__}: {exc}")
    time.sleep(10)

print("dbt: данные не появились за 10 минут", file=sys.stderr)
sys.exit(1)
PY

echo "dbt: собираем модели и тесты"
exec dbt build --project-dir oil_production --profiles-dir .
