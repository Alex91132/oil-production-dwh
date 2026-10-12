-- Вопрос: насколько эффективно работают буровые установки — сколько пробурено,
--         как долго длятся переезды и какая доля времени уходит на простой?
-- Техники: LAG для интервала между соседними назначениями (переезд + ожидание),
--          JOIN по условию «дата внутри периода», расчёт KPI.

WITH a AS (
    SELECT
        ra.rig_id,
        ra.pad_id,
        ra.start_date,
        ra.end_date,
        ra.start_date - lag(ra.end_date) OVER (PARTITION BY ra.rig_id ORDER BY ra.start_date)  AS gap_days
    FROM ops.rig_assignments ra
),
drilled AS (
    SELECT a.rig_id, count(w.well_id) AS wells, sum(w.md_m) AS meters
    FROM a
    JOIN ops.wells w
      ON w.pad_id = a.pad_id
     AND w.spud_date BETWEEN a.start_date AND a.end_date
    GROUP BY a.rig_id
)
SELECT
    r.name                                                         AS rig,
    r.contractor,
    count(*)                                                       AS pads,
    d.wells,
    round(d.meters / 1000, 1)                                      AS meters_km,
    round(d.meters / sum(a.end_date - a.start_date + 1))           AS m_per_rig_day,
    round(avg(a.gap_days), 1)                                      AS avg_gap_days,
    round(100.0 * sum(a.end_date - a.start_date + 1)
          / (max(a.end_date) - min(a.start_date) + 1), 1)          AS utilization_pct
FROM a
JOIN ops.rigs r USING (rig_id)
JOIN drilled d USING (rig_id)
GROUP BY r.name, r.contractor, d.wells, d.meters
ORDER BY meters_km DESC;
