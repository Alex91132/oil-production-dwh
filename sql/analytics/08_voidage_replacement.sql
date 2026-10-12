-- Вопрос: насколько закачка воды компенсирует отбор жидкости на каждом
--         месторождении — по годам и нарастающим итогом?
--         (компенсация < 100 % ведёт к падению пластового давления)
-- Техники: объединение двух фактовых таблиц через агрегацию на общем зерне
--          (месторождение × месяц), LEFT JOIN, оконная функция поверх агрегатов
--          (SUM(SUM(...)) OVER ...).
-- Упрощение: объёмы сравниваются в поверхностных условиях, без объёмного коэффициента.

WITH prod AS (
    SELECT v.field_name, m.month, sum(m.oil_m3 + m.water_m3) AS liquid_m3
    FROM ops.mv_monthly_production m
    JOIN ops.v_wells v USING (well_id)
    GROUP BY v.field_name, m.month
),
inj AS (
    SELECT v.field_name, date_trunc('month', di.inj_date)::date AS month, sum(di.water_m3) AS inj_m3
    FROM ops.daily_injection di
    JOIN ops.v_wells v USING (well_id)
    GROUP BY v.field_name, date_trunc('month', di.inj_date)
)
SELECT
    p.field_name,
    date_part('year', p.month)::int                                     AS year,
    round(sum(p.liquid_m3) / 1000)                                      AS liquid_th_m3,
    round(sum(coalesce(i.inj_m3, 0)) / 1000)                            AS injection_th_m3,
    round(100 * sum(coalesce(i.inj_m3, 0)) / sum(p.liquid_m3), 1)       AS compensation_pct,
    round(100 * sum(sum(coalesce(i.inj_m3, 0))) OVER cum
              / sum(sum(p.liquid_m3))           OVER cum, 1)            AS cum_compensation_pct
FROM prod p
LEFT JOIN inj i USING (field_name, month)
GROUP BY p.field_name, date_part('year', p.month)
WINDOW cum AS (PARTITION BY p.field_name ORDER BY date_part('year', p.month))
ORDER BY p.field_name, year;
