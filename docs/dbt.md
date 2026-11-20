# dbt: слой трансформаций

## Зачем

Airflow отвечает за **доставку** данных: забирает месяц из PostgreSQL и атомарно
подменяет партиции в ClickHouse. dbt отвечает за **логику**: из сырых фактов и
измерений собирает витрины и проверяет их тестами. Это ELT: загрузка и
трансформация разделены, у каждой части свой инструмент.

```
PostgreSQL ──► Airflow ──► ClickHouse dwh.*        (сырьё: fact_*, dim_*)
                                │
                                ├──► dbt staging  ──► база dwh_staging (view)
                                └──► dbt marts    ──► база dwh_marts  (table)
                                                        │
                                                        └──► Superset (дашборд)
```

Витрину `mart_field_monthly` строит **только dbt**: в `clickhouse/init/01_schema.sql`
её DDL больше нет, а задача `build_mart` из DAG удалена. Один источник правды.

## Структура

```
dbt/
├── oil_production/
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/                     # view, база dwh_staging
│   │   │   ├── stg_production_daily.sql
│   │   │   ├── stg_injection_daily.sql
│   │   │   └── stg_dim_well.sql
│   │   ├── marts/                       # table, база dwh_marts
│   │   │   ├── mart_field_monthly.sql
│   │   │   └── mart_well_performance.sql
│   │   └── schema.yml                   # описания, тесты, источники
│   └── tests/                           # кастомные assertions
│       ├── assert_oil_non_negative.sql
│       ├── assert_watercut_bounds.sql
│       ├── assert_well_exists_in_dim.sql
│       ├── assert_mart_matches_facts.sql
│       └── assert_mart_grain_unique.sql
├── profiles.yml                         # подключение через env-переменные
└── ci_seed.sql, ci_load.py              # данные для CI
```

## Модели

| Модель | Слой | Зерно | Что внутри |
|---|---|---|---|
| `stg_production_daily` | staging | скважина × день | переименование, приведение типов, флаг `is_producing` |
| `stg_injection_daily` | staging | скважина × день | то же для закачки |
| `stg_dim_well` | staging | скважина | атрибуты и иерархия для JOIN |
| `mart_field_monthly` | mart | месторождение × месяц | добыча, обводнённость, компенсация, фонд |
| `mart_well_performance` | mart | скважина × месяц | дебит, обводнённость, темп падения |

**Формулы витрины** (совпадают с прежним SQL, поэтому числа не изменились):

```
liquid_m3    = oil_t * 1000 / oil_density + water_m3   -- тонны → м³ по плотности
watercut     = water_m3 / liquid_m3
compensation = injection_m3 / liquid_m3
oil_t_per_day = oil_t / число дней в месяце
```

Складывать `oil_t` (тонны) с `water_m3` (кубометры) нельзя — получается число без
физического смысла, и тест на диапазон `[0, 1]` тогда проходит всегда. Поэтому
пересчёт через плотность обязателен.

## Тесты

`dbt build` запускает модели и тесты в одном прогоне: собрать витрину с битыми
данными нельзя.

| Тест | Что проверяет |
|---|---|
| `not_null` | ключи и метрики без пропусков |
| `unique` | нет дублей скважин в измерении |
| `accepted_values` | только известные `purpose` и `trajectory` |
| `assert_oil_non_negative` | добыча не отрицательна |
| `assert_watercut_bounds` | обводнённость в `[0, 1]` при `liquid_m3 > 0` |
| `assert_well_exists_in_dim` | каждый факт имеет измерение |
| `assert_mart_matches_facts` | суммы витрины равны суммам фактов |
| `assert_mart_grain_unique` | одна строка на месторождение × месяц |

## Как запускать

Внутри Airflow (как в конвейере):

```bash
docker compose exec -T airflow dbt build \
  --project-dir /opt/airflow/dbt/oil_production \
  --profiles-dir /opt/airflow/dbt
```

Или из корня проекта:

```bash
make dbt        # dbt build
make dbt-test   # только тесты
```

В DAG это задача `dbt_build`: выполняется после `load_production`/`load_injection`
и `refresh_reference`, перед `reconcile`. Если dbt упал — конвейер останавливается.

## CI

Workflow `dbt.yml` поднимает ClickHouse сервис-контейнером, загружает
`dbt/ci_seed.sql` через `dbt/ci_load.py` (HTTP ClickHouse не принимает несколько
операторов за раз) и запускает `dbt build`. Ожидаемый результат: `PASS=32, ERROR=0`.

Отдельно `tests/test_dbt_project.py` проверяет структуру без запуска dbt: что нет
`target:` в `dbt_project.yml` (dbt 1.12 падает), что все `ref` и `source`
существуют, что у каждой модели есть тесты и что в DAG не вернулся ручной
`build_mart`.

## Ограничения

- **Исторические атрибуты.** `dim_well_scd` пишет версии с даты запуска: прошлые
  изменения из текущего источника не восстановить (нужен CDC или архивные срезы).
- **Мягкие удаления.** Скважина, пропавшая из источника, версию не закрывает.
- **Модели пока не читают `dim_well_scd`** — история версий загружается, но в
  витринах используется текущее значение `purpose`. Следующий шаг — point-in-time
  join в `mart_well_performance`, чтобы назначение бралось на дату месяца.
