-- =============================================================================
-- SCD Type 2: история изменений атрибутов скважины.
--
-- В dim_well (Type 1) при изменении атрибута старое значение теряется.
-- Здесь каждая версия строки живёт с valid_from / valid_to / is_current:
--   скважина 2015: purpose='producer', formation='ЮС2'
--   скважина 2018: purpose='injector'  (перевод под закачку)
--
-- Зачем: аналитика ГТМ «до/после перевода», отчёт по фондам на дату,
--        присоединение фактов к правильной версии измерения.
-- =============================================================================

CREATE TABLE IF NOT EXISTS dwh.dim_well_scd
(
    -- технический ключ версии (surrogate key)
    well_scd_id      UInt64,
    -- естественный ключ (business key)
    well_id          UInt32,
    well_name        String,
    -- иерархия
    field_id         UInt16,
    field_name       LowCardinality(String),
    region           LowCardinality(String),
    pad_id           UInt32,
    pad_name         LowCardinality(String),
    formation_id     UInt16,
    formation_name   LowCardinality(String),
    -- изменяемые атрибуты (отслеживаем SCD 2)
    purpose          LowCardinality(String),      -- producer / injector
    trajectory       LowCardinality(String),      -- directional / horizontal / multilateral
    -- неизменяемые атрибуты (SCD 0 — копируем в каждую версию)
    spud_date        Date,
    start_date       Date,
    md_m             Float32,
    -- управление версиями
    valid_from       Date,                        -- с какой даты версия действительна
    valid_to         Date DEFAULT toDate('9999-12-31'),
    is_current       Bool DEFAULT true,
    -- аудит
    loaded_at        DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (well_id, valid_from);

-- -----------------------------------------------------------------------------
-- Пример запроса: фонд добывающих скважин на конкретную дату (AS OF)
-- -----------------------------------------------------------------------------
-- SELECT count() AS producers
-- FROM dwh.dim_well_scd
-- WHERE is_current = 1                    -- или: valid_from <= '2020-06-01' AND valid_to > '2020-06-01'
--   AND purpose = 'producer';

-- -----------------------------------------------------------------------------
-- Пример: скважины, сменившие назначение (переведены под закачку)
-- -----------------------------------------------------------------------------
-- SELECT
--     well_name,
--     groupArray(purpose)    AS transitions,
--     groupArray(valid_from) AS dates,
--     count()                AS versions
-- FROM dwh.dim_well_scd
-- GROUP BY well_name
-- HAVING versions > 1
-- ORDER BY versions DESC;

-- -----------------------------------------------------------------------------
-- Пример: присоединение факта к правильной версии измерения (point-in-time join)
-- -----------------------------------------------------------------------------
-- SELECT
--     f.prod_date,
--     f.well_id,
--     f.oil_t,
--     d.purpose,
--     d.formation_name
-- FROM dwh.fact_production_daily AS f
-- JOIN dwh.dim_well_scd AS d
--   ON f.well_id = d.well_id
--  AND f.prod_date >= d.valid_from
--  AND f.prod_date <  d.valid_to
-- LIMIT 100;
