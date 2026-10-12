-- Вопрос: у каких скважин в последнем месяце резко выросла обводнённость?
--         Это кандидаты на ремонтно-изоляционные работы (РИР).
-- Техники: скользящее окно по предыдущим строкам
--          (ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING), подсчёт размера окна,
--          защита от деления на ноль (NULLIF).

WITH wc AS (
    SELECT
        m.well_id,
        m.month,
        m.water_m3 / nullif(m.water_m3 + m.oil_m3, 0)  AS watercut
    FROM ops.mv_monthly_production m
    WHERE m.days_on >= 20                      -- только полноценно отработанные месяцы
),
trend AS (
    SELECT
        well_id,
        month,
        watercut,
        avg(watercut) OVER prev6  AS wc_prev6,
        count(*)      OVER prev6  AS n_prev
    FROM wc
    WINDOW prev6 AS (PARTITION BY well_id ORDER BY month
                     ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING)
)
SELECT
    v.field_name,
    v.well_name,
    v.formation_name,
    t.month,
    round(100 * t.wc_prev6, 1)                 AS wc_prev6_pct,
    round(100 * t.watercut, 1)                 AS wc_now_pct,
    round(100 * (t.watercut - t.wc_prev6), 1)  AS delta_pp
FROM trend t
JOIN ops.v_wells v USING (well_id)
WHERE t.month = (SELECT max(month) FROM ops.mv_monthly_production)
  AND t.n_prev = 6                             -- полная история за полгода
  AND t.watercut - t.wc_prev6 > 0.03           -- рост более чем на 3 п.п.
ORDER BY delta_pp DESC
LIMIT 15;
