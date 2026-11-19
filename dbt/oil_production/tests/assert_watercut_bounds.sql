-- Тест: обводнённость в диапазоне [0, 1]
SELECT *
FROM {{ ref('mart_field_monthly') }}
WHERE watercut < 0 OR watercut > 1
