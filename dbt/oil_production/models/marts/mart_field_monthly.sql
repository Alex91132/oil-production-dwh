{{ config(materialized='table') }}

-- Витрина: добыча и закачка по месторождению × месяц.
-- Формулы совпадают с витриной, которую строил Airflow (`MART_SQL` в DAG):
--   liquid_m3    = oil_t * 1000 / oil_density + water_m3   (тонны → м³ по плотности)
--   watercut     = water_m3 / liquid_m3
--   compensation = injection_m3 / liquid_m3
--
-- Важно: добыча и закачка агрегируются **по месторождению отдельно** и только
-- потом соединяются по (месяц, месторождение). Джойн по well_id был бы ошибкой:
-- нагнетательные и добывающие — разные скважины, и закачка обнулилась бы.

WITH production AS (
    SELECT
        p.month                    AS month,
        w.field_name               AS field_name,
        uniqExactIf(p.well_id, p.producing_days > 0) AS producing_wells,
        sum(p.oil_t)               AS oil_t,
        sum(p.water_m3)            AS water_m3,
        sum(p.gas_km3)             AS gas_km3,
        sum(p.oil_t * 1000 / w.oil_density + p.water_m3) AS liquid_m3
    FROM (
        SELECT
            toStartOfMonth(date)        AS month,
            well_id,
            sum(oil_t)                  AS oil_t,
            sum(water_m3)               AS water_m3,
            sum(gas_km3)                AS gas_km3,
            sum(if(is_producing, 1, 0)) AS producing_days
        FROM {{ ref('stg_production_daily') }}
        GROUP BY month, well_id
    ) AS p
    INNER JOIN {{ ref('stg_dim_well') }} AS w ON w.well_id = p.well_id
    GROUP BY month, field_name
),

injection AS (
    SELECT
        i.month                    AS month,
        w.field_name               AS field_name,
        uniqExactIf(i.well_id, i.injection_m3 > 0) AS injecting_wells,
        sum(i.injection_m3)        AS injection_m3
    FROM (
        SELECT
            toStartOfMonth(date) AS month,
            well_id,
            sum(injection_m3)    AS injection_m3
        FROM {{ ref('stg_injection_daily') }}
        GROUP BY month, well_id
    ) AS i
    INNER JOIN {{ ref('stg_dim_well') }} AS w ON w.well_id = i.well_id
    GROUP BY month, field_name
)

SELECT
    p.month                                    AS month,
    p.field_name                               AS field_name,
    p.producing_wells                          AS producing_wells,
    ifNull(i.injecting_wells, 0)               AS injecting_wells,
    p.oil_t                                    AS oil_t,
    p.water_m3                                 AS water_m3,
    p.gas_km3                                  AS gas_km3,
    p.liquid_m3                                AS liquid_m3,
    ifNull(i.injection_m3, 0)                  AS injection_m3,
    p.oil_t / dateDiff('day', p.month, addMonths(p.month, 1)) AS oil_t_per_day,
    if(p.liquid_m3 > 0, p.water_m3 / p.liquid_m3, 0)          AS watercut,
    if(p.liquid_m3 > 0, ifNull(i.injection_m3, 0) / p.liquid_m3, 0) AS compensation
FROM production AS p
LEFT JOIN injection AS i ON p.month = i.month AND p.field_name = i.field_name
