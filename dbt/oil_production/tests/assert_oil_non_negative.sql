-- Тест: добыча нефти не может быть отрицательной
SELECT *
FROM {{ ref('stg_production_daily') }}
WHERE oil_t < 0
