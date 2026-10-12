-- =============================================================================
-- Операционная (OLTP) модель данных нефтедобычи.
-- Нормализована до 3НФ; целостность обеспечивается на уровне БД:
-- внешние ключи, CHECK, исключающие ограничения (EXCLUDE) на пересечение периодов.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ops;
SET search_path TO ops, public;

-- Нужно для EXCLUDE-ограничений, где сравнивается и скаляр (=), и диапазон (&&)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ---------------------------------------------------------------------------
-- Справочники
-- ---------------------------------------------------------------------------

-- Месторождения
CREATE TABLE fields (
    field_id    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text     NOT NULL UNIQUE,
    region      text     NOT NULL,
    discovered  smallint NOT NULL CHECK (discovered BETWEEN 1900 AND 2100)
);

-- Пласты (объекты разработки) месторождения
CREATE TABLE formations (
    formation_id     smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_id         smallint     NOT NULL REFERENCES fields,
    name             text         NOT NULL,
    top_depth_m      numeric(7,1) NOT NULL CHECK (top_depth_m > 0),
    porosity         numeric(4,3) NOT NULL CHECK (porosity BETWEEN 0 AND 0.5),
    permeability_md  numeric(8,2) NOT NULL CHECK (permeability_md > 0),
    oil_density      numeric(5,1) NOT NULL CHECK (oil_density BETWEEN 700 AND 1000), -- кг/м3
    UNIQUE (field_id, name),
    UNIQUE (field_id, formation_id)          -- цель для составного FK из wells
);

-- Кустовые площадки
CREATE TABLE pads (
    pad_id    integer  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_id  smallint NOT NULL REFERENCES fields,
    name      text     NOT NULL,
    lat       numeric(8,5) NOT NULL CHECK (lat BETWEEN -90 AND 90),
    lon       numeric(8,5) NOT NULL CHECK (lon BETWEEN -180 AND 180),
    UNIQUE (field_id, name),
    UNIQUE (field_id, pad_id)                -- цель для составного FK из wells
);

-- Стабильные наборы значений — ENUM; справочник с атрибутами — отдельная таблица
CREATE TYPE well_purpose    AS ENUM ('producer', 'injector');
CREATE TYPE well_trajectory AS ENUM ('directional', 'horizontal', 'multilateral'); -- ННС / ГС / МЗС

-- Скважины.
-- field_id хранится намеренно: составные FK гарантируют, что куст и пласт
-- скважины принадлежат одному и тому же месторождению.
CREATE TABLE wells (
    well_id       integer  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_id      smallint NOT NULL,
    pad_id        integer  NOT NULL,
    formation_id  smallint NOT NULL,
    name          text     NOT NULL,
    purpose       well_purpose    NOT NULL,
    trajectory    well_trajectory NOT NULL,
    spud_date     date     NOT NULL,          -- начало бурения
    start_date    date     NOT NULL,          -- ввод в эксплуатацию
    md_m          numeric(7,1) NOT NULL CHECK (md_m > 0),  -- глубина по стволу
    UNIQUE (field_id, name),
    CHECK (start_date >= spud_date),
    FOREIGN KEY (field_id, pad_id)       REFERENCES pads (field_id, pad_id),
    FOREIGN KEY (field_id, formation_id) REFERENCES formations (field_id, formation_id)
);

-- Виды геолого-технических мероприятий (ГТМ)
CREATE TABLE intervention_types (
    type_code  text PRIMARY KEY,
    name_ru    text NOT NULL UNIQUE,
    category   text NOT NULL CHECK (category IN ('стимуляция', 'ремонт', 'реконструкция'))
);

-- ---------------------------------------------------------------------------
-- События
-- ---------------------------------------------------------------------------

-- Проведённые ГТМ. На одной скважине мероприятия не могут пересекаться по датам.
CREATE TABLE interventions (
    intervention_id  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    well_id          integer NOT NULL REFERENCES wells,
    type_code        text    NOT NULL REFERENCES intervention_types,
    start_date       date    NOT NULL,
    end_date         date    NOT NULL,
    cost_mln_rub     numeric(8,2) NOT NULL CHECK (cost_mln_rub > 0),
    CHECK (end_date >= start_date),
    EXCLUDE USING gist (
        well_id WITH =,
        daterange(start_date, end_date, '[]') WITH &&
    )
);

-- Буровые установки
CREATE TABLE rigs (
    rig_id      smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    contractor  text NOT NULL
);

-- График работы буровых по кустам.
-- Буровая физически не может стоять на двух кустах одновременно — это
-- гарантирует EXCLUDE-ограничение, а не код приложения.
CREATE TABLE rig_assignments (
    assignment_id  integer  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rig_id         smallint NOT NULL REFERENCES rigs,
    pad_id         integer  NOT NULL REFERENCES pads,
    start_date     date     NOT NULL,
    end_date       date     NOT NULL,
    CHECK (end_date >= start_date),
    EXCLUDE USING gist (
        rig_id WITH =,
        daterange(start_date, end_date, '[]') WITH &&
    )
);

-- ---------------------------------------------------------------------------
-- Факты (самые объёмные таблицы)
-- ---------------------------------------------------------------------------

-- Суточная добыча. Партиционирована по годам: запросы за период читают
-- только нужные партиции (partition pruning), старые годы легко архивировать.
CREATE TABLE daily_production (
    well_id    integer      NOT NULL REFERENCES wells,
    prod_date  date         NOT NULL,
    hours_on   numeric(4,1) NOT NULL CHECK (hours_on BETWEEN 0 AND 24),
    oil_t      numeric(9,3) NOT NULL CHECK (oil_t    >= 0),   -- нефть, т
    water_m3   numeric(9,3) NOT NULL CHECK (water_m3 >= 0),   -- вода, м3
    gas_km3    numeric(9,3) NOT NULL CHECK (gas_km3  >= 0),   -- попутный газ, тыс. м3
    PRIMARY KEY (well_id, prod_date)
) PARTITION BY RANGE (prod_date);

DO $$
BEGIN
    FOR y IN 2021..2026 LOOP
        EXECUTE format(
            'CREATE TABLE ops.daily_production_%s PARTITION OF ops.daily_production
             FOR VALUES FROM (%L) TO (%L)',
            y, make_date(y, 1, 1), make_date(y + 1, 1, 1));
    END LOOP;
END $$;

-- Страховочная партиция: данные вне ожидаемых лет не потеряются
CREATE TABLE daily_production_default PARTITION OF daily_production DEFAULT;

-- Суточная закачка воды в нагнетательные скважины (объём меньше — без партиций)
CREATE TABLE daily_injection (
    well_id     integer      NOT NULL REFERENCES wells,
    inj_date    date         NOT NULL,
    hours_on    numeric(4,1) NOT NULL CHECK (hours_on BETWEEN 0 AND 24),
    water_m3    numeric(9,3) NOT NULL CHECK (water_m3 >= 0),
    PRIMARY KEY (well_id, inj_date)
);

COMMENT ON SCHEMA ops IS 'Операционные данные нефтедобычи (синтетические)';
COMMENT ON TABLE ops.daily_production IS 'Суточная добыча по скважинам, партиции по годам';
COMMENT ON TABLE ops.interventions    IS 'Геолого-технические мероприятия (ГТМ)';
COMMENT ON TABLE ops.rig_assignments  IS 'График движения буровых установок по кустам';
