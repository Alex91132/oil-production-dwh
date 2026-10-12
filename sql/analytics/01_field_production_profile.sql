-- Вопрос: как менялась годовая добыча каждого месторождения, какова его доля
--         в общей добыче и сколько уже добыто нарастающим итогом?
-- Техники: CTE, оконные функции LAG / SUM OVER, именованное окно (WINDOW),
--          рамка окна ROWS UNBOUNDED PRECEDING.

WITH yearly AS (
    SELECT
        w.field_name,
        date_part('year', m.month)::int  AS year,
        sum(m.oil_t) / 1000              AS oil_kt
    FROM ops.mv_monthly_production m
    JOIN ops.v_wells w USING (well_id)
    WHERE m.month < date '2026-01-01'          -- только полные годы
    GROUP BY w.field_name, date_part('year', m.month)
)
SELECT
    field_name,
    year,
    round(oil_kt, 1)                                                     AS oil_kt,
    round(100 * oil_kt / sum(oil_kt) OVER (PARTITION BY year), 1)        AS share_pct,
    round(100 * (oil_kt / nullif(lag(oil_kt) OVER w, 0) - 1), 1)         AS yoy_pct,
    round(sum(oil_kt) OVER (w ROWS UNBOUNDED PRECEDING), 1)              AS cumulative_kt
FROM yearly
WINDOW w AS (PARTITION BY field_name ORDER BY year)
ORDER BY field_name, year;
