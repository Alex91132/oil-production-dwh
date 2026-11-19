-- Суточная закачка: стандартизация.
-- Источник — dwh.fact_injection_daily, загружается Airflow DAG.

{{ config(materialized='view') }}

SELECT
    inj_date               AS date,
    toDate(inj_date)       AS date_typed,
    well_id                AS well_id,
    toDecimal64(hours_on, 1)  AS hours_on,
    toDecimal64(water_m3, 3)  AS injection_m3,
    hours_on > 0           AS is_injecting
FROM {{ source('dwh', 'fact_injection_daily') }}
