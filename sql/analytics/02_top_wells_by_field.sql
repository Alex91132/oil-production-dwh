-- Вопрос: какие пять скважин каждого месторождения дали больше всего нефти
--         за последние 12 месяцев и какую долю добычи месторождения они обеспечивают?
-- Техники: ранжирование RANK() внутри группы (PARTITION BY), доля от итога группы,
--          агрегат с FILTER, отбор «топ-N в каждой группе».

WITH last12 AS (
    SELECT
        dp.well_id,
        sum(dp.oil_t)                                    AS oil_t,
        avg(dp.oil_t) FILTER (WHERE dp.hours_on = 24)    AS avg_rate_t_d   -- только полные сутки
    FROM ops.daily_production dp
    WHERE dp.prod_date > (SELECT max(prod_date) FROM ops.daily_production) - interval '12 months'
    GROUP BY dp.well_id
),
ranked AS (
    SELECT
        w.field_name, w.well_name, w.pad_name, w.trajectory,
        l.oil_t, l.avg_rate_t_d,
        rank()        OVER (PARTITION BY w.field_name ORDER BY l.oil_t DESC) AS rnk,
        l.oil_t / sum(l.oil_t) OVER (PARTITION BY w.field_name)             AS share
    FROM last12 l
    JOIN ops.v_wells w USING (well_id)
)
SELECT
    field_name,
    rnk,
    well_name,
    pad_name,
    trajectory,
    round(oil_t / 1000, 2)     AS oil_kt,
    round(avg_rate_t_d, 1)     AS avg_rate_t_d,
    round(100 * share, 1)      AS share_of_field_pct
FROM ranked
WHERE rnk <= 5
ORDER BY field_name, rnk;
