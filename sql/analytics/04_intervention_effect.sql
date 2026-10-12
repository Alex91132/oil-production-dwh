-- Вопрос: какие ГТМ реально дают прирост добычи, как часто они успешны
--         и во сколько обходится тонна дополнительной нефти?
-- Техники: LATERAL-подзапросы (окно «до» и «после» для каждого мероприятия),
--          использование PK-индекса (well_id, prod_date) для точечных выборок,
--          агрегаты над булевыми условиями.
--
-- Методика: дебит «до» — средний за 30 суток до начала ГТМ, «после» — за 90 суток
-- после окончания; берутся только полные сутки работы (hours_on = 24).
-- Успех — прирост более 10 %. Упрощение: естественное падение добычи
-- за период не вычитается, поэтому эффект слегка занижен.

WITH effect AS (
    SELECT
        i.intervention_id,
        i.type_code,
        i.cost_mln_rub,
        before.rate  AS rate_before,
        after.rate   AS rate_after
    FROM ops.interventions i
    CROSS JOIN LATERAL (
        SELECT avg(dp.oil_t) AS rate
        FROM ops.daily_production dp
        WHERE dp.well_id = i.well_id
          AND dp.prod_date BETWEEN i.start_date - 30 AND i.start_date - 1
          AND dp.hours_on = 24
    ) before
    CROSS JOIN LATERAL (
        SELECT avg(dp.oil_t) AS rate
        FROM ops.daily_production dp
        WHERE dp.well_id = i.well_id
          AND dp.prod_date BETWEEN i.end_date + 1 AND i.end_date + 90
          AND dp.hours_on = 24
    ) after
)
SELECT
    t.name_ru                                                    AS intervention,
    count(*)                                                     AS n,
    round(avg(e.rate_before), 1)                                 AS rate_before_t_d,
    round(avg(e.rate_after), 1)                                  AS rate_after_t_d,
    round(avg(e.rate_after - e.rate_before), 1)                  AS uplift_t_d,
    round(100 * avg((e.rate_after > e.rate_before * 1.1)::int))  AS success_pct,
    round(avg(e.cost_mln_rub), 1)                                AS avg_cost_mln_rub,
    -- затраты на тонну дополнительной нефти за 90 суток эффекта
    round(sum(e.cost_mln_rub) * 1e6
          / nullif(sum(greatest(e.rate_after - e.rate_before, 0)) * 90, 0))  AS rub_per_extra_t
FROM effect e
JOIN ops.intervention_types t USING (type_code)
WHERE e.rate_before IS NOT NULL
  AND e.rate_after  IS NOT NULL
GROUP BY t.name_ru
ORDER BY uplift_t_d DESC;
