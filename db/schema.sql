CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    date_received DATE,
    last_name TEXT,
    first_name TEXT,
    middle_name TEXT,
    previous_last_name TEXT,
    sex TEXT,
    birth_date DATE,
    birth_place TEXT,
    snils TEXT,
    passport_number TEXT,
    passport_issued TEXT,

    phone_mobile TEXT,
    phone_2 TEXT,
    phone_3 TEXT,
    email_1 TEXT,
    email_2 TEXT,
    email_upgo TEXT,

    residence_area TEXT,

    appointment_date DATE,
    dismissal_date DATE,
    confirmed_experience_years NUMERIC(6,1),

    source_info TEXT,

    education_text TEXT,
    education_count INTEGER,
    work_text TEXT,
    extra_info_text TEXT
);
