-- Тест: витрина ничего не теряет и не дублирует по сравнению с фактами.
-- Если JOIN с измерением или группировка отбрасывает строки — суммы разойдутся.

WITH fact AS (
    SELECT sum(oil_t) AS oil_t, sum(water_m3) AS water_m3
    FROM {{ ref('stg_production_daily') }}
),

mart AS (
    SELECT sum(oil_t) AS oil_t, sum(water_m3) AS water_m3
    FROM {{ ref('mart_field_monthly') }}
)

SELECT
    fact.oil_t   AS fact_oil,
    mart.oil_t   AS mart_oil,
    fact.water_m3 AS fact_water,
    mart.water_m3 AS mart_water
FROM fact
CROSS JOIN mart
WHERE abs(fact.oil_t - mart.oil_t) > 0.01
   OR abs(fact.water_m3 - mart.water_m3) > 0.01
