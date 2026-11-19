-- Тест: обводнённость физически осмысленна.
-- Считается как water_m3 / liquid_m3, где liquid_m3 — в м³ (тонны нефти
-- переведены по плотности). Поэтому значения вне [0, 1] — ошибка формулы.

SELECT
    month,
    field_name,
    watercut
FROM {{ ref('mart_field_monthly') }}
WHERE liquid_m3 > 0
  AND (watercut < 0 OR watercut > 1)
