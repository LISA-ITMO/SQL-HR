SET datestyle = 'ISO, DMY';

DROP TABLE IF EXISTS candidates_raw;

CREATE TABLE candidates_raw (
    "Дата поступления документов" TEXT,
    "Фамилия" TEXT,
    "Имя" TEXT,
    "Отчество" TEXT,
    "Направление" TEXT,
    "Дата рождения" TEXT,
    "Соответствует?" TEXT,
    "Дата передачи на оценку" TEXT,
    "Номер телефона (моб)" TEXT,
    "Номер телефона 2" TEXT,
    "Номер телефона 3" TEXT,
    "Паспорт (серия, номер)" TEXT,
    "Паспорт (кем и когда выдан)" TEXT,
    "e-mail (1)" TEXT,
    "e-mail (2)" TEXT,
    "Образование (ВУЗ)" TEXT,
    "Образование (наименование)" TEXT,
    "Вид" TEXT,
    "Наличие диплома" TEXT,
    "2 Образование (ВУЗ)" TEXT,
    "2 Образование (наименование)" TEXT,
    "2 Вид" TEXT,
    "2 Наличие диплома" TEXT,
    "3 Образование (ВУЗ)" TEXT,
    "3 Образование (наименование)" TEXT,
    "3 Вид" TEXT,
    "3 Наличие диплома" TEXT,
    "Организация" TEXT,
    "Подразделение" TEXT,
    "Должность" TEXT,
    "Вид контракта" TEXT,
    "Дата назначения" TEXT,
    "Дата увольнения" TEXT,
    "Дополнительная информация" TEXT,
    "Вывод" TEXT,
    "Статус" TEXT,
    "Исполнитель" TEXT,
    "Work (орган)" TEXT,
    "Work (должность)" TEXT,
    "Work (дата запроса)" TEXT,
    "Work (дата направления)" TEXT,
    "Work (результат)" TEXT,
    "Work (кто направил)" TEXT,
    "2_Work (орган)" TEXT,
    "2_Work (должность)" TEXT,
    "2_Work (дата запроса)" TEXT,
    "2_Work (Дата направления)" TEXT,
    "2_Work (результат)" TEXT,
    "2_Work (кто направил)" TEXT,
    "3_Work (орган)" TEXT,
    "3_Work (должность)" TEXT,
    "3_Work (дата запроса)" TEXT,
    "3_Work (дата направления)" TEXT,
    "3_Work (результат)" TEXT,
    "3_Work (кто направил)" TEXT,
    "4_Work (орган)" TEXT,
    "4_Work (должность)" TEXT,
    "4_Work (дата запроса)" TEXT,
    "4_Work (дата направления)" TEXT,
    "4_Work (результат)" TEXT,
    "4_Work (кто направил)" TEXT,
    "Трудоустройство" TEXT,
    "Место рождения" TEXT,
    "Аттестация (обучение МКР)" TEXT,
    "Место проживания (район)" TEXT,
    "Готовность к работе" TEXT,
    "СНИЛС" TEXT,
    "Месяц (NEW)" TEXT,
    "Пол" TEXT,
    "1 Диплом с отличием" TEXT,
    "2 Диплом с отличием" TEXT,
    "3 Диплом с отличием" TEXT,
    "Доп_инфо_МКР" TEXT,
    "Псих_испол_3" TEXT,
    "Дата поступления заключения" TEXT,
    "Скорость передачи на оценку" TEXT,
    "Дата заполнения" TEXT,
    "Д" TEXT,
    "О" TEXT,
    "РЯ_13/22" TEXT,
    "РасЧис_м3" TEXT,
    "УстЗак_м3" TEXT,
    "ЧисРяд_м3" TEXT,
    "ЛогВерб_м4" TEXT,
    "КейсТекст_м4" TEXT,
    "КейсЗад_м1" TEXT,
    "1_этап_25_40" TEXT,
    "Word_м10" TEXT,
    "Excell_м10" TEXT,
    "1_2_этапы_38_60" TEXT,
    "2_этап_13_20" TEXT,
    "Общий интеллект_m18" TEXT,
    "Цель оценки" TEXT,
    "Комментарии по трудоустройству" TEXT,
    "Откуда вы узнали о МКР?" TEXT,
    "Дата тестирования (1 этап)" TEXT,
    "Вывод по тестированию (1 этап)" TEXT,
    "Дата собеседования (2 этап)" TEXT,
    "Вывод по собеседованию (2 этап)" TEXT,
    "Особенности оценки" TEXT,
    "Информация о ранних подачах" TEXT,
    "Последняя прежняя фамилия" TEXT,
    "e-mail УПГО" TEXT,
    "Комментарии из заключения (особенности)" TEXT,
    "Сфера интересов" TEXT,
    "Комментарии из заключения (рекомендованная деятельность)" TEXT,
    "Комментарии из заключения (Не рекомендованная деятельность)" TEXT,
    "Группа отправки (Контр_упр)" TEXT
);

COPY candidates_raw (
    "Дата поступления документов",
    "Фамилия",
    "Имя",
    "Отчество",
    "Направление",
    "Дата рождения",
    "Соответствует?",
    "Дата передачи на оценку",
    "Номер телефона (моб)",
    "Номер телефона 2",
    "Номер телефона 3",
    "Паспорт (серия, номер)",
    "Паспорт (кем и когда выдан)",
    "e-mail (1)",
    "e-mail (2)",
    "Образование (ВУЗ)",
    "Образование (наименование)",
    "Вид",
    "Наличие диплома",
    "2 Образование (ВУЗ)",
    "2 Образование (наименование)",
    "2 Вид",
    "2 Наличие диплома",
    "3 Образование (ВУЗ)",
    "3 Образование (наименование)",
    "3 Вид",
    "3 Наличие диплома",
    "Организация",
    "Подразделение",
    "Должность",
    "Вид контракта",
    "Дата назначения",
    "Дата увольнения",
    "Дополнительная информация",
    "Вывод",
    "Статус",
    "Исполнитель",
    "Work (орган)",
    "Work (должность)",
    "Work (дата запроса)",
    "Work (дата направления)",
    "Work (результат)",
    "Work (кто направил)",
    "2_Work (орган)",
    "2_Work (должность)",
    "2_Work (дата запроса)",
    "2_Work (Дата направления)",
    "2_Work (результат)",
    "2_Work (кто направил)",
    "3_Work (орган)",
    "3_Work (должность)",
    "3_Work (дата запроса)",
    "3_Work (дата направления)",
    "3_Work (результат)",
    "3_Work (кто направил)",
    "4_Work (орган)",
    "4_Work (должность)",
    "4_Work (дата запроса)",
    "4_Work (дата направления)",
    "4_Work (результат)",
    "4_Work (кто направил)",
    "Трудоустройство",
    "Место рождения",
    "Аттестация (обучение МКР)",
    "Место проживания (район)",
    "Готовность к работе",
    "СНИЛС",
    "Месяц (NEW)",
    "Пол",
    "1 Диплом с отличием",
    "2 Диплом с отличием",
    "3 Диплом с отличием",
    "Доп_инфо_МКР",
    "Псих_испол_3",
    "Дата поступления заключения",
    "Скорость передачи на оценку",
    "Дата заполнения",
    "Д",
    "О",
    "РЯ_13/22",
    "РасЧис_м3",
    "УстЗак_м3",
    "ЧисРяд_м3",
    "ЛогВерб_м4",
    "КейсТекст_м4",
    "КейсЗад_м1",
    "1_этап_25_40",
    "Word_м10",
    "Excell_м10",
    "1_2_этапы_38_60",
    "2_этап_13_20",
    "Общий интеллект_m18",
    "Цель оценки",
    "Комментарии по трудоустройству",
    "Откуда вы узнали о МКР?",
    "Дата тестирования (1 этап)",
    "Вывод по тестированию (1 этап)",
    "Дата собеседования (2 этап)",
    "Вывод по собеседованию (2 этап)",
    "Особенности оценки",
    "Информация о ранних подачах",
    "Последняя прежняя фамилия",
    "e-mail УПГО",
    "Комментарии из заключения (особенности)",
    "Сфера интересов",
    "Комментарии из заключения (рекомендованная деятельность)",
    "Комментарии из заключения (Не рекомендованная деятельность)",
    "Группа отправки (Контр_упр)"
)
FROM '/data/candidates_clean.csv'
WITH (
    FORMAT csv,
    HEADER true,
    DELIMITER ';',
    ENCODING 'UTF8',
    NULL ''
);

INSERT INTO candidates (
    date_received,
    last_name,
    first_name,
    middle_name,
    previous_last_name,
    sex,
    birth_date,
    birth_place,
    snils,
    passport_number,
    passport_issued,
    phone_mobile,
    phone_2,
    phone_3,
    email_1,
    email_2,
    email_upgo,
    residence_area,
    appointment_date,
    dismissal_date,
    confirmed_experience_years,
    source_info,
    education_text,
    education_count,
    work_text,
    extra_info_text
)
SELECT
    NULLIF("Дата поступления документов", '')::date,
    NULLIF("Фамилия", ''),
    NULLIF("Имя", ''),
    NULLIF("Отчество", ''),
    NULLIF("Последняя прежняя фамилия", ''),
    NULLIF("Пол", ''),
    NULLIF("Дата рождения", '')::date,
    NULLIF("Место рождения", ''),
    NULLIF("СНИЛС", ''),
    NULLIF("Паспорт (серия, номер)", ''),
    NULLIF("Паспорт (кем и когда выдан)", ''),
    NULLIF("Номер телефона (моб)", ''),
    NULLIF("Номер телефона 2", ''),
    NULLIF("Номер телефона 3", ''),
    NULLIF("e-mail (1)", ''),
    NULLIF("e-mail (2)", ''),
    NULLIF("e-mail УПГО", ''),
    NULLIF("Место проживания (район)", ''),
    NULLIF("Дата назначения", '')::date,
    NULLIF("Дата увольнения", '')::date,
    CASE
        WHEN NULLIF("Дата назначения", '')::date IS NOT NULL
            AND NULLIF("Дата увольнения", '')::date IS NOT NULL
        THEN ROUND(((NULLIF("Дата увольнения", '')::date - NULLIF("Дата назначения", '')::date)::numeric) / 365.25, 1)
        ELSE NULL
    END,
    NULLIF("Откуда вы узнали о МКР?", ''),
    NULLIF(
        CONCAT_WS(
            E'\n',
            CASE
                WHEN NULLIF("Образование (ВУЗ)", '') IS NOT NULL
                    OR NULLIF("Образование (наименование)", '') IS NOT NULL
                    OR LOWER(NULLIF("Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да')
                    OR LOWER(NULLIF("1 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да')
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("Образование (ВУЗ)", '') IS NOT NULL THEN '1. ВУЗ: ' || "Образование (ВУЗ)" END,
                    CASE WHEN NULLIF("Образование (наименование)", '') IS NOT NULL THEN 'направление: ' || "Образование (наименование)" END,
                    CASE WHEN LOWER(NULLIF("Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Есть диплом' END,
                    CASE WHEN LOWER(NULLIF("1 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Диплом с отличием' END
                )
            END,
            CASE
                WHEN NULLIF("2 Образование (ВУЗ)", '') IS NOT NULL
                    OR NULLIF("2 Образование (наименование)", '') IS NOT NULL
                    OR LOWER(NULLIF("2 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да')
                    OR LOWER(NULLIF("2 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да')
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("2 Образование (ВУЗ)", '') IS NOT NULL THEN '2. ВУЗ: ' || "2 Образование (ВУЗ)" END,
                    CASE WHEN NULLIF("2 Образование (наименование)", '') IS NOT NULL THEN 'направление: ' || "2 Образование (наименование)" END,
                    CASE WHEN LOWER(NULLIF("2 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Есть диплом' END,
                    CASE WHEN LOWER(NULLIF("2 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Диплом с отличием' END
                )
            END,
            CASE
                WHEN NULLIF("3 Образование (ВУЗ)", '') IS NOT NULL
                    OR NULLIF("3 Образование (наименование)", '') IS NOT NULL
                    OR LOWER(NULLIF("3 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да')
                    OR LOWER(NULLIF("3 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да')
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("3 Образование (ВУЗ)", '') IS NOT NULL THEN '3. ВУЗ: ' || "3 Образование (ВУЗ)" END,
                    CASE WHEN NULLIF("3 Образование (наименование)", '') IS NOT NULL THEN 'направление: ' || "3 Образование (наименование)" END,
                    CASE WHEN LOWER(NULLIF("3 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Есть диплом' END,
                    CASE WHEN LOWER(NULLIF("3 Диплом с отличием", '')) IN ('true', 't', '1', 'yes', 'да') THEN 'Диплом с отличием' END
                )
            END
        ),
        ''
    ),
    (
        CASE WHEN LOWER(NULLIF("Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 1 ELSE 0 END
        + CASE WHEN LOWER(NULLIF("2 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 1 ELSE 0 END
        + CASE WHEN LOWER(NULLIF("3 Наличие диплома", '')) IN ('true', 't', '1', 'yes', 'да') THEN 1 ELSE 0 END
    )::int,
    NULLIF(
        CONCAT_WS(
            E'\n',
            CASE
                WHEN NULLIF("Организация", '') IS NOT NULL
                    OR NULLIF("Подразделение", '') IS NOT NULL
                    OR NULLIF("Должность", '') IS NOT NULL
                    OR NULLIF("Вид контракта", '') IS NOT NULL
                THEN CONCAT_WS(
                    ' ',
                    'Текущая работа:',
                    CONCAT_WS(
                        '; ',
                        CASE WHEN NULLIF("Организация", '') IS NOT NULL THEN 'Организация: ' || "Организация" END,
                        CASE WHEN NULLIF("Подразделение", '') IS NOT NULL THEN 'Подразделение: ' || "Подразделение" END,
                        CASE WHEN NULLIF("Должность", '') IS NOT NULL THEN 'Должность: ' || "Должность" END,
                        CASE WHEN NULLIF("Вид контракта", '') IS NOT NULL THEN 'Вид контракта: ' || "Вид контракта" END
                    )
                )
            END,
            CASE
                WHEN NULLIF("Трудоустройство", '') IS NOT NULL
                THEN 'Трудоустройство: ' || "Трудоустройство"
            END,
            CASE
                WHEN NULLIF("Work (орган)", '') IS NOT NULL
                    OR NULLIF("Work (должность)", '') IS NOT NULL
                    OR NULLIF("Work (результат)", '') IS NOT NULL
                    OR NULLIF("2_Work (орган)", '') IS NOT NULL
                    OR NULLIF("2_Work (должность)", '') IS NOT NULL
                    OR NULLIF("2_Work (результат)", '') IS NOT NULL
                    OR NULLIF("3_Work (орган)", '') IS NOT NULL
                    OR NULLIF("3_Work (должность)", '') IS NOT NULL
                    OR NULLIF("3_Work (результат)", '') IS NOT NULL
                    OR NULLIF("4_Work (орган)", '') IS NOT NULL
                    OR NULLIF("4_Work (должность)", '') IS NOT NULL
                    OR NULLIF("4_Work (результат)", '') IS NOT NULL
                THEN 'Предыдущий опыт:'
            END,
            CASE
                WHEN NULLIF("Work (орган)", '') IS NOT NULL
                    OR NULLIF("Work (должность)", '') IS NOT NULL
                    OR NULLIF("Work (результат)", '') IS NOT NULL
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("Work (орган)", '') IS NOT NULL THEN 'Работа 1 (орган): ' || "Work (орган)" END,
                    CASE WHEN NULLIF("Work (должность)", '') IS NOT NULL THEN 'Работа 1 (должность): ' || "Work (должность)" END,
                    CASE WHEN NULLIF("Work (результат)", '') IS NOT NULL THEN 'Работа 1 (результат): ' || "Work (результат)" END
                )
            END,
            CASE
                WHEN NULLIF("2_Work (орган)", '') IS NOT NULL
                    OR NULLIF("2_Work (должность)", '') IS NOT NULL
                    OR NULLIF("2_Work (результат)", '') IS NOT NULL
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("2_Work (орган)", '') IS NOT NULL THEN 'Работа 2 (орган): ' || "2_Work (орган)" END,
                    CASE WHEN NULLIF("2_Work (должность)", '') IS NOT NULL THEN 'Работа 2 (должность): ' || "2_Work (должность)" END,
                    CASE WHEN NULLIF("2_Work (результат)", '') IS NOT NULL THEN 'Работа 2 (результат): ' || "2_Work (результат)" END
                )
            END,
            CASE
                WHEN NULLIF("3_Work (орган)", '') IS NOT NULL
                    OR NULLIF("3_Work (должность)", '') IS NOT NULL
                    OR NULLIF("3_Work (результат)", '') IS NOT NULL
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("3_Work (орган)", '') IS NOT NULL THEN 'Работа 3 (орган): ' || "3_Work (орган)" END,
                    CASE WHEN NULLIF("3_Work (должность)", '') IS NOT NULL THEN 'Работа 3 (должность): ' || "3_Work (должность)" END,
                    CASE WHEN NULLIF("3_Work (результат)", '') IS NOT NULL THEN 'Работа 3 (результат): ' || "3_Work (результат)" END
                )
            END,
            CASE
                WHEN NULLIF("4_Work (орган)", '') IS NOT NULL
                    OR NULLIF("4_Work (должность)", '') IS NOT NULL
                    OR NULLIF("4_Work (результат)", '') IS NOT NULL
                THEN CONCAT_WS(
                    '; ',
                    CASE WHEN NULLIF("4_Work (орган)", '') IS NOT NULL THEN 'Работа 4 (орган): ' || "4_Work (орган)" END,
                    CASE WHEN NULLIF("4_Work (должность)", '') IS NOT NULL THEN 'Работа 4 (должность): ' || "4_Work (должность)" END,
                    CASE WHEN NULLIF("4_Work (результат)", '') IS NOT NULL THEN 'Работа 4 (результат): ' || "4_Work (результат)" END
                )
            END
        ),
        ''
    ),
    NULLIF(
        CONCAT_WS(
            '; ',
            CASE WHEN NULLIF("Направление", '') IS NOT NULL THEN 'Направление: ' || "Направление" END,
            CASE WHEN NULLIF("Дополнительная информация", '') IS NOT NULL THEN 'Дополнительная информация: ' || "Дополнительная информация" END,
            CASE WHEN NULLIF("Вывод", '') IS NOT NULL THEN 'Вывод: ' || "Вывод" END,
            CASE WHEN NULLIF("Вывод по тестированию (1 этап)", '') IS NOT NULL THEN 'Вывод по тестированию (1 этап): ' || "Вывод по тестированию (1 этап)" END,
            CASE WHEN NULLIF("Вывод по собеседованию (2 этап)", '') IS NOT NULL THEN 'Вывод по собеседованию (2 этап): ' || "Вывод по собеседованию (2 этап)" END,
            CASE WHEN NULLIF("Особенности оценки", '') IS NOT NULL THEN 'Особенности оценки: ' || "Особенности оценки" END,
            CASE WHEN NULLIF("Комментарии из заключения (особенности)", '') IS NOT NULL THEN 'Комментарии из заключения (особенности): ' || "Комментарии из заключения (особенности)" END,
            CASE WHEN NULLIF("Комментарии из заключения (рекомендованная деятельность)", '') IS NOT NULL THEN 'Комментарии из заключения (рекомендованная деятельность): ' || "Комментарии из заключения (рекомендованная деятельность)" END,
            CASE WHEN NULLIF("Комментарии по трудоустройству", '') IS NOT NULL THEN 'Комментарии по трудоустройству: ' || "Комментарии по трудоустройству" END,
            CASE WHEN NULLIF("Информация о ранних подачах", '') IS NOT NULL THEN 'Информация о ранних подачах: ' || "Информация о ранних подачах" END,
            CASE WHEN NULLIF("Сфера интересов", '') IS NOT NULL THEN 'Сфера интересов: ' || "Сфера интересов" END
        ),
        ''
    )
FROM candidates_raw;
