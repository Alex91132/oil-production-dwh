-- Витрина: эффективность скважин по месяцам (decline, watercut, компенсация).
-- Строится поверх staging-моделей; объединяет добычу, закачку и атрибуты скважины.

{{ config(materialized='table') }}

WITH monthly AS (
    SELECT
        toStartOfMonth(date)  AS month,
        well_id,
        sum(oil_t)            AS oil_t,
        sum(water_m3)         AS water_m3,
        sum(hours_on)         AS hours_worked
    FROM {{ ref('stg_production_daily') }}
    GROUP BY month, well_id
),

with_prev AS (
    SELECT
        *,
        lagInFrame(oil_t) OVER (
            PARTITION BY well_id ORDER BY month
            ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
        ) AS oil_t_prev
    FROM monthly
)

SELECT
    m.month,
    m.well_id,
    w.well_name,
    w.field_name,
    w.formation_name,
    w.purpose,
    w.trajectory,
    m.oil_t,
    m.water_m3,
    m.hours_worked,
    -- обводнённость
    if(m.oil_t + m.water_m3 > 0,
       m.water_m3 / (m.oil_t + m.water_m3), NULL) AS watercut,
    -- темп падения (decline rate) относительно прошлого месяца
    if(p.oil_t_prev > 0 AND p.oil_t > 0,
       1 - p.oil_t / p.oil_t_prev, NULL) AS decline_rate,
    -- суточный дебит
    if(m.hours_worked > 0,
       m.oil_t / (m.hours_worked / 24), NULL) AS oil_rate_t_per_day
FROM with_prev AS p
INNER JOIN monthly AS m ON p.month = m.month AND p.well_id = m.well_id
INNER JOIN {{ ref('stg_dim_well') }} AS w ON m.well_id = w.well_id
