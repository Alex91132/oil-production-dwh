-- Тест: зерно витрины — одна строка на месторождение × месяц.
-- Дубли означают, что GROUP BY неполный (например, добавили колонку в SELECT,
-- но забыли в GROUP BY).

SELECT
    month,
    field_name,
    count() AS rows
FROM {{ ref('mart_field_monthly') }}
GROUP BY month, field_name
HAVING rows > 1
