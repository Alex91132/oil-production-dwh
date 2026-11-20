-- Минимальные данные для CI: dbt build проверяет модели и тесты без Airflow.
-- Схема повторяет dwh.* из docker-compose (ClickHouse init).
CREATE DATABASE IF NOT EXISTS dwh;

CREATE TABLE IF NOT EXISTS dwh.dim_well
(
    well_id UInt32,
    well_name String,
    field_id UInt16,
    field_name LowCardinality(String),
    region LowCardinality(String),
    pad_id UInt32,
    pad_name LowCardinality(String),
    formation_id UInt16,
    formation_name LowCardinality(String),
    oil_density Float32,
    purpose LowCardinality(String),
    trajectory LowCardinality(String),
    spud_date Date,
    start_date Date,
    md_m Float32
)
ENGINE = MergeTree ORDER BY well_id;

CREATE TABLE IF NOT EXISTS dwh.fact_production_daily
(
    prod_date Date,
    well_id UInt32,
    hours_on Float32,
    oil_t Float32,
    water_m3 Float32,
    gas_km3 Float32
)
ENGINE = MergeTree ORDER BY (prod_date, well_id);

CREATE TABLE IF NOT EXISTS dwh.fact_injection_daily
(
    inj_date Date,
    well_id UInt32,
    hours_on Float32,
    water_m3 Float32
)
ENGINE = MergeTree ORDER BY (inj_date, well_id);

INSERT INTO dwh.dim_well VALUES
    (1, 'W-1', 1, 'Field A', 'North', 10, 'Pad 10', 7, 'ЮС2', 850, 'producer', 'horizontal', '2014-05-01', '2015-01-01', 3200),
    (2, 'W-2', 1, 'Field A', 'North', 10, 'Pad 10', 7, 'ЮС2', 850, 'producer', 'directional', '2014-06-01', '2015-02-01', 2800),
    (3, 'W-3', 1, 'Field A', 'North', 11, 'Pad 11', 9, 'ЮС3', 840, 'injector', 'horizontal', '2016-03-01', '2016-09-01', 3100);

CREATE TABLE IF NOT EXISTS dwh.dim_well_scd
(
    well_scd_id UInt64,
    well_id UInt32,
    well_name String,
    field_id UInt16,
    field_name LowCardinality(String),
    region LowCardinality(String),
    pad_id UInt32,
    pad_name LowCardinality(String),
    formation_id UInt16,
    formation_name LowCardinality(String),
    purpose LowCardinality(String),
    trajectory LowCardinality(String),
    spud_date Date32,
    start_date Date32,
    md_m Float32,
    valid_from Date32,
    valid_to Date32,
    is_current Bool
)
ENGINE = MergeTree ORDER BY (well_id, valid_from);

INSERT INTO dwh.dim_well_scd VALUES
    (1, 1, 'W-1', 1, 'Field A', 'North', 10, 'Pad 10', 7, 'ЮС2', 'producer', 'horizontal',
     '2014-05-01', '2015-01-01', 3200, '2015-01-01', '2299-12-31', 1),
    (2, 2, 'W-2', 1, 'Field A', 'North', 10, 'Pad 10', 7, 'ЮС2', 'producer', 'directional',
     '2014-06-01', '2015-02-01', 2800, '2015-02-01', '2020-12-01', 0),
    (3, 2, 'W-2', 1, 'Field A', 'North', 10, 'Pad 10', 7, 'ЮС2', 'injector', 'directional',
     '2014-06-01', '2015-02-01', 2800, '2020-12-01', '2299-12-31', 1),
    (4, 3, 'W-3', 1, 'Field A', 'North', 11, 'Pad 11', 9, 'ЮС3', 'injector', 'horizontal',
     '2016-03-01', '2016-09-01', 3100, '2016-09-01', '2299-12-31', 1);

INSERT INTO dwh.fact_production_daily VALUES
    ('2021-01-01', 1, 24, 100, 20, 5),
    ('2021-01-02', 1, 24, 98, 22, 5),
    ('2021-01-03', 1, 12, 40, 15, 2),
    ('2021-01-01', 2, 24, 60, 40, 3),   -- обводнённость 0,5 в пересчёте на м³
    ('2021-01-03', 2, 0, 0, 0, 0);      -- простой: нулевые значения

INSERT INTO dwh.fact_injection_daily VALUES
    ('2021-01-01', 3, 24, 120),
    ('2021-01-02', 3, 24, 118),
    ('2021-01-03', 3, 24, 121);
