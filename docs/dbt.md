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
| `mart_well_performance` | mart | скважина × месяц | дебит, обводнённость, темп падения, назначение **на дату** из SCD |

**Формулы витрины** (совпадают с прежним SQL, поэтому числа не изменились):

```
liquid_m3    = oil_t * 1000 / oil_density + water_m3   -- тонны → м³ по плотности
watercut     = water_m3 / liquid_m3
compensation = injection_m3 / liquid_m3
oil_t_per_day = oil_t / число дней в месяце
```

Добыча и закачка агрегируются **по месторождению отдельно** и соединяются по
(месяц, месторождение). Джойн по `well_id` был бы ошибкой: нагнетательные и
добывающие — разные скважины, и закачка обнулилась бы. Эта ошибка была в первой
версии модели; теперь её ловит тест `assert_injection_not_lost`.

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
| `assert_watercut_null_only_without_liquid` | `watercut` = NULL ровно тогда, когда жидкости не было |
| `assert_injection_not_lost` | сумма закачки в витрине равна сумме по фактам |

## Как запускать

Внутри Airflow (как в конвейере):

```bash
make dbt        # dbt build (подставляет параметры подключения сам)
make dbt-test   # только тесты
```

Напрямую, если нужно передать свои параметры:

```bash
docker compose exec -T \
  -e CLICKHOUSE_HOST=clickhouse -e CLICKHOUSE_PORT=8123 \
  -e CLICKHOUSE_USER=dwh -e CLICKHOUSE_PASSWORD=dwh -e CLICKHOUSE_DB=dwh \
  airflow dbt build --project-dir /opt/airflow/dbt/oil_production --profiles-dir /opt/airflow/dbt
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
- **Покрытие историей зависит от накопленных версий.** `mart_well_performance`
  делает point-in-time join к `dim_well_scd`: колонка `purpose_on_date` — назначение
  на дату месяца, `purpose_from_history` = 1, если версия нашлась. Пока история
  начинается с даты первой загрузки, у большинства месяцев версии нет — тогда
  берётся текущее назначение (fallback), и флаг это показывает.

Point-in-time join в модели:

```sql
LEFT JOIN {{ source('dwh', 'dim_well_scd') }} AS v
       ON v.well_id = p.well_id
      AND p.month >= v.valid_from     -- интервал полуоткрытый,
      AND p.month <  v.valid_to       -- поэтому версия всегда одна
```

Проверка на стенде: 17 765 строк «скважина × месяц» — столько же, сколько до join
(размножения нет); у 69 строк `purpose_from_history = 1`, и там `purpose_on_date`
отличается от текущего `purpose` — ровно тот случай, ради которого нужен SCD.
