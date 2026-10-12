-- Вопрос: какая доля фонда даёт 50 / 80 / 95 % добычи за последний год?
--         (принцип Парето: на каких скважинах держится добыча)
-- Техники: накопленная доля через SUM OVER (ORDER BY ...) / SUM OVER (),
--          агрегат с FILTER, генерация порогов через VALUES.

WITH last_year AS (
    SELECT well_id, sum(oil_t) AS oil_t
    FROM ops.mv_monthly_production
    WHERE month > (SELECT max(month) FROM ops.mv_monthly_production) - interval '12 months'
    GROUP BY well_id
    HAVING sum(oil_t) > 0
),
cumulative AS (
    SELECT
        well_id,
        sum(oil_t)   OVER (ORDER BY oil_t DESC, well_id) / sum(oil_t) OVER ()  AS cum_share,
        row_number() OVER (ORDER BY oil_t DESC, well_id)                        AS rn,
        count(*)     OVER ()                                                    AS wells_total
    FROM last_year
)
SELECT
    t.threshold_pct                                                       AS oil_share_pct,
    min(c.rn) FILTER (WHERE c.cum_share >= t.threshold_pct / 100.0)       AS wells_needed,
    max(c.wells_total)                                                    AS wells_total,
    round(100.0 * min(c.rn) FILTER (WHERE c.cum_share >= t.threshold_pct / 100.0)
          / max(c.wells_total), 1)                                        AS wells_share_pct
FROM cumulative c
CROSS JOIN (VALUES (50), (80), (95)) AS t (threshold_pct)
GROUP BY t.threshold_pct
ORDER BY t.threshold_pct;
