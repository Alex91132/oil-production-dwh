-- Суточная добыча: стандартизация имён и типов.
-- Источник — dwh.fact_production_daily, загружается Airflow DAG.

{{ config(materialized='view') }}

SELECT
    prod_date              AS date,
    toDate(prod_date)      AS date_typed,
    well_id                AS well_id,
    toDecimal64(hours_on, 1)  AS hours_on,
    toDecimal64(oil_t, 3)     AS oil_t,
    toDecimal64(water_m3, 3)  AS water_m3,
    toDecimal64(gas_km3, 3)   AS gas_km3,
    hours_on > 0           AS is_producing
FROM {{ source('dwh', 'fact_production_daily') }}
