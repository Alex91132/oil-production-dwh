FROM postgres:16-alpine

# Скрипты из /docker-entrypoint-initdb.d выполняются один раз при создании БД
COPY db/init/ /docker-entrypoint-initdb.d/

# Аналитические запросы доступны внутри контейнера: psql -f /sql/analytics/...
COPY sql/ /sql/
