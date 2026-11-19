{{ config(materialized='table') }}

-- Витрина: эффективность скважин по месяцам.
-- Каждая колонка явно алиасится: в ClickHouse `m.oil_t` без алиаса даёт
-- колонку с именем «m.oil_t», и потребитель не может обратиться к `oil_t`.

WITH monthly AS (
    SELECT
        toStartOfMonth(date)  AS month,
        well_id,
        sum(oil_t)            AS oil_t,
        sum(water_m3)         AS water_m3,
        sum(gas_km3)          AS gas_km3,
        sum(hours_on)         AS hours_worked
    FROM {{ ref('stg_production_daily') }}
    GROUP BY month, well_id
),

with_prev AS (
    SELECT
        month,
        well_id,
        oil_t,
        water_m3,
        gas_km3,
        hours_worked,
        lagInFrame(oil_t) OVER (PARTITION BY well_id ORDER BY month) AS oil_t_prev
    FROM monthly
)

SELECT
    p.month                                   AS month,
    p.well_id                                 AS well_id,
    w.well_name                               AS well_name,
    w.field_name                              AS field_name,
    w.formation_name                          AS formation_name,
    w.purpose                                 AS purpose,
    w.trajectory                              AS trajectory,
    p.oil_t                                   AS oil_t,
    p.water_m3                                AS water_m3,
    p.hours_worked                            AS hours_worked,
    p.oil_t * 1000 / w.oil_density + p.water_m3 AS liquid_m3,
    if(p.oil_t * 1000 / w.oil_density + p.water_m3 > 0,
       p.water_m3 / (p.oil_t * 1000 / w.oil_density + p.water_m3), NULL) AS watercut,
    if(p.oil_t_prev > 0 AND p.oil_t > 0,
       1 - p.oil_t / p.oil_t_prev, NULL)      AS decline_rate,
    if(p.hours_worked > 0,
       p.oil_t / (p.hours_worked / 24), NULL) AS oil_rate_t_per_day
FROM with_prev AS p
INNER JOIN {{ ref('stg_dim_well') }} AS w ON p.well_id = w.well_id
