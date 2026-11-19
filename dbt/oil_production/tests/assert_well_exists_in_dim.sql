-- Тест: каждый well_id в фактах существует в измерении dim_well
-- (referential integrity — аналог FK, но на уровне данных, не схемы)
SELECT DISTINCT f.well_id
FROM {{ ref('stg_production_daily') }} AS f
LEFT JOIN {{ ref('stg_dim_well') }} AS d ON f.well_id = d.well_id
WHERE d.well_id IS NULL
