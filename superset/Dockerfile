FROM apache/superset:6.1.0

USER root
# Драйвер ClickHouse (SQLAlchemy-диалект clickhousedb://) в окружение Superset
RUN uv pip install --python /app/.venv/bin/python --no-cache clickhouse-connect==1.10.0

# Каталог /app/pythonpath уже в PYTHONPATH образа: superset_config.py подхватится сам
COPY superset/superset_config.py /app/pythonpath/superset_config.py

# Скрипт «дашборд как код» и SQL виртуальных датасетов (единый источник с sql/clickhouse)
COPY superset/bootstrap/ /app/bootstrap/
COPY sql/clickhouse/ /app/bootstrap/sql/
USER superset
