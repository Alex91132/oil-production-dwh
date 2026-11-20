-- Тест: watercut = NULL ровно тогда, когда жидкости не было.
-- Для остановленных скважин (liquid_m3 = 0) обводнённость не определена — это
-- не пропуск данных, а отсутствие явления. Тест ловит и обратную ошибку:
-- NULL там, где жидкость была.

SELECT
    month,
    well_id,
    liquid_m3,
    watercut
FROM {{ ref('mart_well_performance') }}
WHERE (liquid_m3 = 0 AND watercut IS NOT NULL)
   OR (liquid_m3 > 0 AND watercut IS NULL)
