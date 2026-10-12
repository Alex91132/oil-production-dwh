-- Проверки качества данных: каждая строка — правило, violations должен быть 0.
-- То, что нельзя выразить ограничениями схемы, проверяется запросами.

SELECT 'добыча до ввода скважины' AS check_name, count(*) AS violations
FROM ops.daily_production dp
JOIN ops.wells w USING (well_id)
WHERE dp.prod_date < w.start_date

UNION ALL
SELECT 'добыча у нагнетательной скважины', count(*)
FROM ops.daily_production dp
JOIN ops.wells w USING (well_id)
WHERE w.purpose = 'injector'

UNION ALL
SELECT 'закачка у добывающей скважины', count(*)
FROM ops.daily_injection di
JOIN ops.wells w USING (well_id)
WHERE w.purpose = 'producer'

UNION ALL
SELECT 'скважина работала во время ГТМ', count(*)
FROM ops.daily_production dp
JOIN ops.interventions i
  ON i.well_id = dp.well_id
 AND dp.prod_date BETWEEN i.start_date AND i.end_date
WHERE dp.hours_on > 0

UNION ALL
SELECT 'добыча при нулевых часах работы', count(*)
FROM ops.daily_production
WHERE hours_on = 0 AND (oil_t > 0 OR water_m3 > 0 OR gas_km3 > 0)

UNION ALL
SELECT 'бурение вне графика буровой', count(*)
FROM ops.wells w
WHERE NOT EXISTS (
    SELECT 1 FROM ops.rig_assignments ra
    WHERE ra.pad_id = w.pad_id
      AND w.spud_date BETWEEN ra.start_date AND ra.end_date)

UNION ALL
SELECT 'строки в страховочной партиции', count(*)
FROM ops.daily_production_default;
