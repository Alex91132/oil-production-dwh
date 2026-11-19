{{ config(materialized='table') }}

-- Витрина: добыча и закачка по месторождению × месяц.
-- Формулы совпадают с витриной, которую строит Airflow (`MART_SQL` в DAG),
-- иначе сверка двух реализаций теряет смысл:
--   liquid_m3   = oil_t * 1000 / oil_density + water_m3   (тонны → м³ по плотности)
--   watercut    = water_m3 / liquid_m3
--   compensation= injection_m3 / liquid_m3

WITH production AS (
    SELECT
        toStartOfMonth(date)  AS month,
        well_id,
        sum(oil_t)            AS oil_t,
        sum(water_m3)         AS water_m3,
        sum(gas_km3)          AS gas_km3,
        sum(if(is_producing, 1, 0)) AS producing_days
    FROM {{ ref('stg_production_daily') }}
    GROUP BY month, well_id
),

injection AS (
    SELECT
        toStartOfMonth(date)  AS month,
        well_id,
        sum(injection_m3)     AS injection_m3
    FROM {{ ref('stg_injection_daily') }}
    GROUP BY month, well_id
),

joined AS (
    SELECT
        p.month                                            AS month,
        w.field_name                                       AS field_name,
        uniqExactIf(p.well_id, p.producing_days > 0)       AS producing_wells,
        uniqExactIf(i.well_id, i.injection_m3 > 0)         AS injecting_wells,
        sum(p.oil_t)                                       AS oil_t,
        sum(p.water_m3)                                    AS water_m3,
        sum(p.gas_km3)                                     AS gas_km3,
        sum(ifNull(i.injection_m3, 0))                     AS injection_m3,
        sum(p.oil_t * 1000 / w.oil_density + p.water_m3)   AS liquid_m3
    FROM production AS p
    INNER JOIN {{ ref('stg_dim_well') }} AS w ON w.well_id = p.well_id
    LEFT JOIN  injection AS i ON p.month = i.month AND p.well_id = i.well_id
    GROUP BY month, field_name
)

SELECT
    month,
    field_name,
    producing_wells,
    injecting_wells,
    oil_t,
    water_m3,
    gas_km3,
    liquid_m3,
    injection_m3,
    oil_t / dateDiff('day', month, addMonths(month, 1))  AS oil_t_per_day,
    if(liquid_m3 > 0, water_m3 / liquid_m3, 0)           AS watercut,
    if(liquid_m3 > 0, injection_m3 / liquid_m3, 0)       AS compensation
FROM joined
