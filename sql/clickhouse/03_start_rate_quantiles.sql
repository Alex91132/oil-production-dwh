-- Вопрос: как распределены стартовые дебиты новых скважин (первые 90 суток)
--         по типу ствола и какая скважина лучшая в каждом типе?
-- Особенности ClickHouse:
--   * quantilesExact(...) — несколько точных квантилей за один проход по данным;
--   * argMax(x, y) — значение x в строке с максимальным y, без подзапроса;
--   * arrayMap с лямбдой — округление элементов массива.

WITH first90 AS (
    SELECT
        w.well_id                                     AS well_id,
        any(concat(w.field_name, ' / ', w.well_name)) AS well,
        any(w.trajectory)                             AS trajectory,
        avg(toFloat64(p.oil_t))                       AS rate
    FROM dwh.fact_production_daily AS p
    INNER JOIN dwh.dim_well AS w ON w.well_id = p.well_id
    WHERE w.purpose = 'producer'
      AND w.start_date >= '2021-01-01'
      AND w.start_date <= (SELECT max(prod_date) FROM dwh.fact_production_daily) - 90
      AND p.prod_date < w.start_date + 90
      AND p.hours_on = 24
    GROUP BY well_id
)
SELECT
    trajectory,
    count()                                                    AS wells,
    arrayMap(x -> round(x, 1), quantilesExact(0.1, 0.5, 0.9)(rate))  AS p10_p50_p90_t_d,
    argMax(well, rate)                                         AS best_well,
    round(max(rate), 1)                                        AS best_rate_t_d
FROM first90
GROUP BY trajectory
ORDER BY quantileExact(0.5)(rate) DESC;
