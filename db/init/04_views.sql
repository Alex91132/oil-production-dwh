-- Представления для удобной аналитики.
SET search_path TO ops, public;

-- Карточка скважины: всё нужное для отчётов без пяти JOIN в каждом запросе
CREATE VIEW v_wells AS
SELECT
    w.well_id,
    w.name          AS well_name,
    f.field_id,
    f.name          AS field_name,
    p.pad_id,
    p.name          AS pad_name,
    fm.formation_id,
    fm.name         AS formation_name,
    fm.oil_density,
    w.purpose,
    w.trajectory,
    w.spud_date,
    w.start_date,
    w.md_m
FROM wells w
JOIN fields     f  ON f.field_id      = w.field_id
JOIN pads       p  ON p.pad_id        = w.pad_id
JOIN formations fm ON fm.formation_id = w.formation_id;

-- Месячная добыча по скважинам.
-- Материализованное представление: агрегат по ~1 млн строк считается один раз
-- при обновлении, а отчёты читают готовые ~30 тыс. строк.
-- Создаётся пустым (WITH NO DATA) и заполняется генератором после загрузки.
CREATE MATERIALIZED VIEW mv_monthly_production AS
SELECT
    dp.well_id,
    date_trunc('month', dp.prod_date)::date            AS month,
    count(*) FILTER (WHERE dp.hours_on > 0)            AS days_on,
    sum(dp.hours_on)                                   AS hours_on,
    sum(dp.oil_t)                                      AS oil_t,
    round(sum(dp.oil_t) * 1000 / fm.oil_density, 3)    AS oil_m3,
    sum(dp.water_m3)                                   AS water_m3,
    sum(dp.gas_km3)                                    AS gas_km3
FROM daily_production dp
JOIN wells      w  ON w.well_id       = dp.well_id
JOIN formations fm ON fm.formation_id = w.formation_id
GROUP BY dp.well_id, date_trunc('month', dp.prod_date), fm.oil_density
WITH NO DATA;

-- Уникальный индекс нужен для REFRESH MATERIALIZED VIEW CONCURRENTLY
-- (обновление без блокировки читателей)
CREATE UNIQUE INDEX idx_mv_monthly_well_month ON mv_monthly_production (well_id, month);
