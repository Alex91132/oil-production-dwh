-- Вопрос: топ-5 скважин каждого месторождения по добыче нефти за последние 12 месяцев.
-- Особенность ClickHouse: LIMIT n BY — «топ-N в каждой группе» без оконной функции.
-- Тот же вопрос в PostgreSQL решается через RANK() OVER (PARTITION BY ...):
-- sql/analytics/02_top_wells_by_field.sql — результаты должны совпасть.

SELECT
    w.field_name                    AS field_name,
    w.well_name                     AS well_name,
    w.pad_name                      AS pad_name,
    w.trajectory                    AS trajectory,
    round(sum(p.oil_t) / 1000, 2)   AS oil_kt
FROM dwh.fact_production_daily AS p
INNER JOIN dwh.dim_well AS w ON w.well_id = p.well_id
WHERE p.prod_date > (SELECT max(prod_date) FROM dwh.fact_production_daily) - INTERVAL 12 MONTH
GROUP BY field_name, well_name, pad_name, trajectory
ORDER BY field_name, oil_kt DESC
LIMIT 5 BY field_name;
