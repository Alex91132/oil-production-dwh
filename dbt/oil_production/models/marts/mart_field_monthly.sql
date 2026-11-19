-- Витрина: добыча и закачка по месторождению × месяц.
-- Заменяет ручной SQL из Airflow: теперь трансформация — dbt,
-- а DAG только загружает сырые данные.

{{ config(materialized='table') }}

WITH production AS (
    SELECT
        toStartOfMonth(date)          AS month,
        well_id,
        sum(oil_t)                    AS oil_t,
        sum(water_m3)                 AS water_m3,
        sum(gas_km3)                  AS gas_km3,
        sum(hours_on)                 AS hours_on,
        countDistinctIf(well_id, hours_on > 0) AS producing_days
    FROM {{ ref('stg_production_daily') }}
    GROUP BY month, well_id
),

injection AS (
    SELECT
        toStartOfMonth(date)          AS month,
        well_id,
        sum(injection_m3)             AS injection_m3
    FROM {{ ref('stg_injection_daily') }}
    GROUP BY month, well_id
),

joined AS (
    SELECT
        p.month,
        w.field_name,
        w.region,
        countDistinct(p.well_id)      AS active_wells,
        sum(p.oil_t)                  AS oil_t,
        sum(p.water_m3)               AS water_m3,
        sum(p.gas_km3)                AS gas_km3,
        sum(ifnull(i.injection_m3, 0)) AS injection_m3
    FROM production AS p
    INNER JOIN {{ ref('stg_dim_well') }} AS w ON p.well_id = w.well_id
    LEFT JOIN  injection AS i ON p.month = i.month AND p.well_id = i.well_id
    GROUP BY p.month, w.field_name, w.region
)

SELECT
    month,
    field_name,
    region,
    active_wells,
    oil_t,
    water_m3,
    gas_km3,
    injection_m3,
    -- вычисляемые метрики
    oil_t + water_m3                        AS liquid_m3_approx,
    if(liquid_m3_approx > 0,
       water_m3 / liquid_m3_approx, 0)      AS watercut,
    if(oil_t + water_m3 > 0,
       injection_m3 / (oil_t + water_m3), NULL) AS compensation
FROM joined
