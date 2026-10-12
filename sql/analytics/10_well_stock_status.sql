-- Вопрос: как менялся фонд скважин по месторождениям на конец каждого года —
--         сколько добывающих, нагнетательных, бездействующих и в бурении?
-- Техники: генерация дат через generate_series, CROSS JOIN «дата × скважина»,
--          коррелированные EXISTS, условная агрегация COUNT(*) FILTER (...).
-- Действующей считается скважина, работавшая хотя бы раз за последние 30 суток.

WITH dates AS (
    SELECT make_date(y, 12, 31) AS on_date FROM generate_series(2021, 2025) AS y
    UNION ALL
    SELECT max(prod_date) FROM ops.daily_production
),
status AS (
    SELECT
        d.on_date,
        w.field_name,
        w.purpose,
        CASE
            WHEN w.start_date > d.on_date THEN 'бурение/освоение'
            WHEN EXISTS (SELECT 1 FROM ops.daily_production p
                         WHERE p.well_id = w.well_id
                           AND p.prod_date BETWEEN d.on_date - 30 AND d.on_date
                           AND p.hours_on > 0)
              OR EXISTS (SELECT 1 FROM ops.daily_injection j
                         WHERE j.well_id = w.well_id
                           AND j.inj_date BETWEEN d.on_date - 30 AND d.on_date
                           AND j.hours_on > 0)
                THEN 'действующая'
            ELSE 'бездействующая'
        END AS status
    FROM dates d
    JOIN ops.v_wells w ON w.spud_date <= d.on_date      -- скважина уже существует
)
SELECT
    on_date,
    field_name,
    count(*) FILTER (WHERE status = 'действующая' AND purpose = 'producer')  AS producing,
    count(*) FILTER (WHERE status = 'действующая' AND purpose = 'injector')  AS injecting,
    count(*) FILTER (WHERE status = 'бездействующая')                         AS idle,
    count(*) FILTER (WHERE status = 'бурение/освоение')                       AS drilling,
    count(*)                                                                  AS total
FROM status
GROUP BY on_date, field_name
ORDER BY field_name, on_date;
