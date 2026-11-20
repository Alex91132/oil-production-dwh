# Команды проекта. Требуется Docker Desktop.
.PHONY: help up down logs test dbt dbt-test scd seed

help:
	@echo "up        — поднять стенд (Postgres, ClickHouse, Airflow, Superset)"
	@echo "down      — остановить (данные сохраняются)"
	@echo "clean     — остановить и удалить тома (чистая инициализация ClickHouse)"
	@echo "test      — pytest (41 тест)"
	@echo "dbt       — dbt build внутри Airflow (модели + тесты)"
	@echo "dbt-test  — только тесты dbt в собранных моделях"
	@echo "scd       — прогон задачи build_dim_well_scd"
	@echo "seed      — залить данные генератором (идемпотентно)"

up:
	docker compose up -d --build

down:
	docker compose down

clean:
	docker compose down -v

logs:
	docker compose logs -f airflow

test:
	python -m pytest -q

dbt:
	docker compose exec -T airflow dbt build --project-dir /opt/airflow/dbt/oil_production --profiles-dir /opt/airflow/dbt

dbt-test:
	docker compose exec -T airflow dbt test --project-dir /opt/airflow/dbt/oil_production --profiles-dir /opt/airflow/dbt

scd:
	docker compose exec -T airflow airflow tasks test oil_dwh_monthly_load build_dim_well_scd 2022-01-01

seed:
	docker compose run --rm generator
