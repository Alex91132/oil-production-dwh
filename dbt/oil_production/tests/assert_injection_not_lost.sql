-- Тест: закачка не потеряна при переходе от фактов к витрине.
-- Именно эта ошибка была допущена в первой версии модели: закачка джойнилась
-- по well_id, а нагнетательные и добывающие — разные скважины, поэтому
-- injection_m3 и compensation обнулялись во всей витрине.

WITH facts AS (
    SELECT sum(injection_m3) AS injection_m3
    FROM {{ ref('stg_injection_daily') }}
),

mart AS (
    SELECT sum(injection_m3) AS injection_m3
    FROM {{ ref('mart_field_monthly') }}
)

SELECT
    facts.injection_m3 AS fact_injection,
    mart.injection_m3  AS mart_injection
FROM facts
CROSS JOIN mart
WHERE abs(facts.injection_m3 - mart.injection_m3) > 0.01
