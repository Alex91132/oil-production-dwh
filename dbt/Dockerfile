FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir dbt-clickhouse==1.9.0

COPY oil_production/ ./oil_production/
COPY profiles.yml ./profiles.yml

# Запуск: dbt build (модели + тесты) при старте контейнера
CMD ["dbt", "build", "--project-dir", "oil_production", "--profiles-dir", "."]
