-- =============================================================================
-- Аналитическое хранилище в ClickHouse: схема «звезда».
--   измерения (dim_*) — денормализованные справочники;
--   факты (fact_*)    — события и суточные замеры;
--   витрины (mart_*)  — готовые агрегаты для отчётов и дашбордов.
-- Наполняется DAG-ом Airflow `oil_dwh_monthly_load`.
-- =============================================================================

CREATE DATABASE IF NOT EXISTS dwh;

-- ---------------------------------------------------------------------------
-- Измерения
-- ---------------------------------------------------------------------------

-- Календарь. Заполняется один раз ниже — на 2010–2030 годы.
CREATE TABLE dwh.dim_date
(
    date           Date,
    year           UInt16,
    quarter        UInt8,
    month          UInt8,
    month_start    Date,
    month_name     LowCardinality(String),
    iso_week       UInt8,
    day_of_week    UInt8,          -- 1 = понедельник
    is_weekend     Bool,
    days_in_month  UInt8
)
ENGINE = MergeTree
ORDER BY date;

INSERT INTO dwh.dim_date
SELECT
    d,
    toYear(d),
    toQuarter(d),
    toMonth(d),
    toStartOfMonth(d),
    ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль',
     'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'][toMonth(d)],
    toISOWeek(d),
    toDayOfWeek(d),
    toDayOfWeek(d) >= 6,
    toDayOfMonth(toLastDayOfMonth(d))
FROM
(
    SELECT toDate('2010-01-01') + number AS d
    FROM numbers(dateDiff('day', toDate('2010-01-01'), toDate('2030-12-31')) + 1)
);

-- Скважина со всеми атрибутами иерархии (месторождение → куст → пласт).
-- В «звезде» иерархия схлопывается в одно измерение: меньше JOIN в отчётах.
-- Обновляется полной перезаливкой с атомарной подменой (EXCHANGE TABLES).
CREATE TABLE dwh.dim_well
(
    well_id         UInt32,
    well_name       String,
    field_id        UInt16,
    field_name      LowCardinality(String),
    region          LowCardinality(String),
    pad_id          UInt32,
    pad_name        LowCardinality(String),
    formation_id    UInt16,
    formation_name  LowCardinality(String),
    oil_density     Float32,
    purpose         LowCardinality(String),
    trajectory      LowCardinality(String),
    spud_date       Date,
    start_date      Date,
    md_m            Float32,
    loaded_at       DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY well_id;

-- ---------------------------------------------------------------------------
-- Факты
-- ---------------------------------------------------------------------------

-- Суточная добыча. Партиция = месяц: именно месяц перезаписывает один запуск DAG.
-- Decimal (а не Float) — чтобы суммы точно сверялись с источником.
CREATE TABLE dwh.fact_production_daily
(
    prod_date  Date,
    well_id    UInt32,
    hours_on   Decimal(4, 1),
    oil_t      Decimal(12, 3),
    water_m3   Decimal(12, 3),
    gas_km3    Decimal(12, 3),
    loaded_at  DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(prod_date)
ORDER BY (well_id, prod_date);

-- Промежуточная таблица той же структуры: месяц сначала собирается здесь,
-- затем атомарно подменяет партицию факта (ALTER TABLE ... REPLACE PARTITION).
CREATE TABLE dwh.stg_production_daily AS dwh.fact_production_daily;

CREATE TABLE dwh.fact_injection_daily
(
    inj_date   Date,
    well_id    UInt32,
    hours_on   Decimal(4, 1),
    water_m3   Decimal(12, 3),
    loaded_at  DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(inj_date)
ORDER BY (well_id, inj_date);

CREATE TABLE dwh.stg_injection_daily AS dwh.fact_injection_daily;

-- Проведённые ГТМ. Атрибуты вида мероприятия денормализованы прямо в факт.
CREATE TABLE dwh.fact_interventions
(
    intervention_id  UInt32,
    well_id          UInt32,
    type_code        LowCardinality(String),
    type_name        LowCardinality(String),
    category         LowCardinality(String),
    start_date       Date,
    end_date         Date,
    duration_days    UInt16,
    cost_mln_rub     Decimal(10, 2),
    loaded_at        DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (well_id, start_date);

-- ---------------------------------------------------------------------------
-- Витрины
-- ---------------------------------------------------------------------------

-- Месторождение × месяц: всё для отчёта о добыче и дашборда
CREATE TABLE dwh.mart_field_monthly
(
    month            Date,
    field_name       LowCardinality(String),
    producing_wells  UInt32,
    injecting_wells  UInt32,
    oil_t            Decimal(18, 3),
    water_m3         Decimal(18, 3),
    gas_km3          Decimal(18, 3),
    liquid_m3        Float64,         -- нефть пересчитана в м3 по плотности + вода
    injection_m3     Decimal(18, 3),
    oil_t_per_day    Float64,
    watercut         Float64,         -- доля воды в жидкости
    compensation     Float64,         -- закачка / отбор жидкости
    built_at         DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(month)
ORDER BY (month, field_name);

CREATE TABLE dwh.stg_mart_field_monthly AS dwh.mart_field_monthly;
