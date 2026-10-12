-- Вопрос: сколько было простоев скважин, какие из них плановые (во время ГТМ),
--         а какие аварийные, и сколько нефти из-за аварийных недобрано?
-- Техники: задача «острова и пропуски» (gaps and islands) через разность
--          даты и ROW_NUMBER, проверка пересечения периодов оператором && для
--          daterange, LATERAL для оценки потерь.

WITH idle_days AS (
    -- Подряд идущие дни простоя дают одинаковую разность «дата − номер строки»
    SELECT
        well_id,
        prod_date,
        prod_date - (row_number() OVER (PARTITION BY well_id ORDER BY prod_date))::int  AS grp
    FROM ops.daily_production
    WHERE hours_on = 0
),
periods AS (
    SELECT well_id, min(prod_date) AS start_date, max(prod_date) AS end_date, count(*) AS days
    FROM idle_days
    GROUP BY well_id, grp
    HAVING count(*) >= 3                       -- простои от трёх суток
),
classified AS (
    SELECT
        p.*,
        CASE WHEN EXISTS (
                 SELECT 1
                 FROM ops.interventions i
                 WHERE i.well_id = p.well_id
                   AND daterange(i.start_date, i.end_date, '[]')
                    && daterange(p.start_date, p.end_date, '[]'))
             THEN 'плановый (ГТМ)'
             ELSE 'аварийный'
        END AS kind,
        rate.oil_t_d
    FROM periods p
    CROSS JOIN LATERAL (                       -- дебит за 30 суток до простоя
        SELECT avg(dp.oil_t) AS oil_t_d
        FROM ops.daily_production dp
        WHERE dp.well_id = p.well_id
          AND dp.prod_date BETWEEN p.start_date - 30 AND p.start_date - 1
          AND dp.hours_on = 24
    ) rate
)
SELECT
    v.field_name,
    c.kind,
    count(*)                                AS episodes,
    sum(c.days)                             AS idle_days,
    round(avg(c.days), 1)                   AS avg_days,
    max(c.days)                             AS max_days,
    round(sum(c.days * c.oil_t_d) / 1000, 1) AS lost_oil_kt
FROM classified c
JOIN ops.v_wells v USING (well_id)
GROUP BY v.field_name, c.kind
ORDER BY v.field_name, c.kind;
