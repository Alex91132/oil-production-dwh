-- Вопрос: сводка по месторождениям за последние 12 месяцев — то, что покажет
--         дашборд: среднесуточная добыча, обводнённость, компенсация отборов
--         и добыча с начала года нарастающим итогом.
-- Особенности: чтение из готовой витрины (сотни строк вместо сотен тысяч);
-- оконная функция в ClickHouse. Окно считается по всей истории во вложенном
-- запросе и только потом фильтруется — иначе итог «с начала года» обрезался бы.

SELECT *
FROM
(
    SELECT
        month,
        field_name,
        producing_wells,
        round(oil_t_per_day, 1)          AS oil_t_d,
        round(100 * watercut, 1)         AS watercut_pct,
        round(100 * compensation, 1)     AS compensation_pct,
        round(sum(oil_t) OVER (PARTITION BY field_name, toYear(month) ORDER BY month) / 1000, 1)
                                         AS ytd_oil_kt
    FROM dwh.mart_field_monthly
)
WHERE month > (SELECT max(month) FROM dwh.mart_field_monthly) - INTERVAL 12 MONTH
ORDER BY field_name, month;
