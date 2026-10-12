FROM clickhouse/clickhouse-server:26.8-alpine

# Скрипты выполняются один раз при первом запуске (пустой каталог данных)
COPY clickhouse/init/ /docker-entrypoint-initdb.d/

# Аналитические запросы к хранилищу: clickhouse-client --queries-file /sql/...
COPY sql/clickhouse/ /sql/clickhouse/
