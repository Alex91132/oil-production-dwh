-- Вопрос: оправдывают ли горизонтальные (ГС) и многозабойные (МЗС) скважины
--         свою сложность — какой у них стартовый дебит в первые 90 суток
--         по сравнению с наклонно-направленными (ННС)?
-- Техники: ROLLUP для подытогов по месторождению и общего итога,
--          GROUPING() для подписи итоговых строк, медиана через PERCENTILE_CONT.

WITH new_wells AS (
    SELECT well_id, field_name, trajectory, start_date
    FROM ops.v_wells
    WHERE purpose = 'producer'
      AND start_date >= date '2021-01-01'
      AND start_date <= (SELECT max(prod_date) FROM ops.daily_production) - 90
),
first90 AS (
    SELECT n.field_name, n.trajectory, n.well_id, avg(dp.oil_t) AS rate
    FROM new_wells n
    JOIN ops.daily_production dp
      ON dp.well_id = n.well_id
     AND dp.prod_date < n.start_date + 90
     AND dp.hours_on = 24
    GROUP BY n.field_name, n.trajectory, n.well_id
)
SELECT
    CASE WHEN grouping(field_name) = 1 THEN 'ИТОГО' ELSE field_name END        AS field,
    CASE WHEN grouping(trajectory) = 1 THEN 'все типы' ELSE trajectory::text END AS trajectory,
    count(*)                                                                    AS wells,
    round(avg(rate), 1)                                                         AS avg_start_rate_t_d,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY rate)::numeric, 1)        AS median_t_d
FROM first90
GROUP BY ROLLUP (field_name, trajectory)
ORDER BY grouping(field_name), field_name, grouping(trajectory), trajectory;
