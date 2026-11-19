-- Измерение «Скважина» с иерархией (месторождение → куст → пласт).
-- Источник — dwh.dim_well, загружается Airflow DAG.

{{ config(materialized='view') }}

SELECT
    well_id,
    well_name,
    field_id,
    field_name,
    region,
    pad_id,
    pad_name,
    formation_id,
    formation_name,
    oil_density,
    purpose,
    trajectory,
    spud_date,
    start_date,
    md_m
FROM {{ source('dwh', 'dim_well') }}
