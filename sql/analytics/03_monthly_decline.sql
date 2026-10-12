-- Вопрос: какой среднесуточный уровень добычи у месторождений в последние 12 месяцев,
--         каков сглаженный тренд и насколько добыча изменилась год к году?
-- Техники: скользящее среднее (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
--          LAG со смещением 12, фильтрация ПОСЛЕ вычисления окон (подзапрос),
--          нормировка на число дней в месяце.

WITH monthly AS (
    SELECT
        w.field_name,
        m.month,
        sum(m.oil_t)
          / extract(day FROM m.month + interval '1 month' - interval '1 day')  AS oil_t_d
    FROM ops.mv_monthly_production m
    JOIN ops.v_wells w USING (well_id)
    GROUP BY w.field_name, m.month
),
with_trend AS (
    SELECT
        field_name,
        month,
        oil_t_d,
        avg(oil_t_d) OVER (PARTITION BY field_name ORDER BY month
                           ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)    AS ma3_t_d,
        lag(oil_t_d, 12) OVER (PARTITION BY field_name ORDER BY month)  AS oil_t_d_year_ago
    FROM monthly
)
-- Фильтр по дате вынесен наружу: если поставить его в monthly, LAG(12)
-- не увидит прошлогодних месяцев и вернёт NULL
SELECT
    field_name,
    month,
    round(oil_t_d, 1)                                            AS oil_t_d,
    round(ma3_t_d, 1)                                            AS ma3_t_d,
    round(100 * (oil_t_d / nullif(oil_t_d_year_ago, 0) - 1), 1)  AS yoy_pct
FROM with_trend
WHERE month > (SELECT max(month) FROM ops.mv_monthly_production) - interval '12 months'
ORDER BY field_name, month;
