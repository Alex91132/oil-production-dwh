-- Индексы. Обоснование каждого решения — в docs/performance.md.
SET search_path TO ops, public;

-- Внешние ключи PostgreSQL не индексирует сам. Без индекса на ссылающейся
-- стороне удаление/изменение родителя ведёт к полному просмотру дочерней таблицы.
CREATE INDEX idx_wells_pad          ON wells (pad_id);
CREATE INDEX idx_wells_formation    ON wells (formation_id);
CREATE INDEX idx_rig_assign_pad     ON rig_assignments (pad_id);

-- Анализ «до/после ГТМ»: ищем мероприятия скважины по дате начала
CREATE INDEX idx_interventions_well_start ON interventions (well_id, start_date);

-- Суточная добыча.
-- PK (well_id, prod_date) уже обслуживает запросы «одна скважина за период».
-- Для запросов «все скважины за период» используем BRIN по дате: данные
-- загружаются в хронологическом порядке (корреляция порядка строк с датой = 1.0),
-- поэтому BRIN в ~30 раз меньше B-tree. pages_per_range = 32 вместо 128
-- по умолчанию подобран замером: в 6 раз меньше лишних перепроверок строк,
-- скорость на уровне B-tree (см. docs/performance.md).
CREATE INDEX idx_daily_prod_date_brin ON daily_production
    USING brin (prod_date) WITH (pages_per_range = 32);
