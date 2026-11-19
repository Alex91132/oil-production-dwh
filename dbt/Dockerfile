FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir dbt-clickhouse==1.9.0

COPY oil_production/ ./oil_production/
COPY profiles.yml ./profiles.yml
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh

# Ждём загрузку данных в ClickHouse и запускаем dbt build (модели + тесты)
CMD ["./entrypoint.sh"]
