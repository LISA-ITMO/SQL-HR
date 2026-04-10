CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE candidates (
    id TEXT PRIMARY KEY,

    -- Демография
    sex            TEXT,
    age            INTEGER,
    birth_date     DATE,

    -- Профессиональный профиль
    desired_position TEXT,
    experience_years NUMERIC(6,2),
    last_employer    TEXT,
    last_position    TEXT,
    work_text        TEXT,

    -- Образование
    education_text TEXT,

    -- Условия работы
    salary         INTEGER,
    employment_type TEXT,
    schedule       TEXT,
    relocation     BOOLEAN,
    business_trips BOOLEAN,

    -- Местоположение
    city TEXT,

    -- Дополнительно
    has_car BOOLEAN
);
