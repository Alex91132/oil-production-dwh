-- Вопрос: как затухает эффект каждого вида ГТМ — во сколько раз дебит выше, чем
--         до мероприятия, через 1, 3, 6 и 12 месяцев после его окончания?
-- Особенности ClickHouse:
--   * ASOF JOIN — к каждому дню добычи присоединяется ПОСЛЕДНЕЕ завершённое ГТМ
--     на этой скважине (в PostgreSQL понадобился бы LATERAL с ORDER BY ... LIMIT 1);
--   * комбинатор -If (medianIf) — «разворот» месяцев в столбцы за один проход.
-- Медиана, а не среднее: при низком дебите «до» (ЗБС на почти выбывших скважинах)
-- отношение очень велико, и среднее перекосили бы единичные выбросы.

WITH
    before AS (
        SELECT
            i.intervention_id         AS intervention_id,
            avg(toFloat64(p.oil_t))   AS rate_before
        FROM dwh.fact_interventions AS i
        INNER JOIN dwh.fact_production_daily AS p ON p.well_id = i.well_id
        WHERE p.prod_date >= i.start_date - 30
          AND p.prod_date <  i.start_date
          AND p.hours_on = 24
        GROUP BY intervention_id
    ),
    after AS (
        SELECT
            i.intervention_id                                           AS intervention_id,
            i.type_name                                                 AS type_name,
            intDiv(dateDiff('day', i.end_date, p.prod_date) - 1, 30) + 1  AS month_after,
            toFloat64(p.oil_t)                                          AS rate
        FROM dwh.fact_production_daily AS p
        ASOF INNER JOIN dwh.fact_interventions AS i
            ON p.well_id = i.well_id AND p.prod_date > i.end_date
        WHERE p.hours_on = 24
    )
SELECT
    a.type_name                                                    AS intervention,
    uniqExact(a.intervention_id)                                   AS n,
    round(medianIf(a.rate / b.rate_before, a.month_after = 1), 2)  AS month_1,
    round(medianIf(a.rate / b.rate_before, a.month_after = 3), 2)  AS month_3,
    round(medianIf(a.rate / b.rate_before, a.month_after = 6), 2)  AS month_6,
    round(medianIf(a.rate / b.rate_before, a.month_after = 12), 2) AS month_12
FROM after AS a
INNER JOIN before AS b ON b.intervention_id = a.intervention_id
WHERE b.rate_before > 0
GROUP BY intervention
ORDER BY month_1 DESC;
