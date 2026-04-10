DROP TABLE IF EXISTS candidates_raw;

CREATE TABLE candidates_raw (
    "candidate_id"                   TEXT,
    "sex"                            TEXT,
    "age"                            TEXT,
    "expected_salary_rub"            TEXT,
    "desired_position"               TEXT,
    "city"                           TEXT,
    "ready_to_relocate"              TEXT,
    "ready_for_business_trips"       TEXT,
    "employment_type"                TEXT,
    "work_schedule"                  TEXT,
    "work_experience"                TEXT,
    "work_experience_years"          TEXT,
    "last_company"                   TEXT,
    "last_job_title"                 TEXT,
    "education_level_and_university" TEXT,
    "resume_updated_at"              TEXT,
    "has_car"                        TEXT
);

COPY candidates_raw (
    "candidate_id",
    "sex",
    "age",
    "expected_salary_rub",
    "desired_position",
    "city",
    "ready_to_relocate",
    "ready_for_business_trips",
    "employment_type",
    "work_schedule",
    "work_experience",
    "work_experience_years",
    "last_company",
    "last_job_title",
    "education_level_and_university",
    "resume_updated_at",
    "has_car"
)
FROM '/data/candidates_clean.csv'
WITH (
    FORMAT csv,
    HEADER true,
    DELIMITER ',',
    ENCODING 'UTF8',
    NULL ''
);

INSERT INTO candidates (
    id,
    sex,
    age,
    desired_position,
    experience_years,
    last_employer,
    last_position,
    work_text,
    education_text,
    salary,
    employment_type,
    schedule,
    relocation,
    business_trips,
    city,
    has_car
)
SELECT
    "candidate_id",
    NULLIF("sex", ''),
    NULLIF("age", '')::integer,
    NULLIF("desired_position", ''),
    NULLIF("work_experience_years", '')::numeric(6,2),
    NULLIF("last_company", ''),
    NULLIF("last_job_title", ''),
    NULLIF(
        CONCAT_WS(
            E'\n',
            NULLIF("work_experience", ''),
            NULLIF(
                CONCAT_WS(' | ',
                    NULLIF("last_company", ''),
                    NULLIF("last_job_title", '')
                ),
                ''
            )
        ),
        ''
    ),
    NULLIF("education_level_and_university", ''),
    NULLIF("expected_salary_rub", '')::integer,
    NULLIF("employment_type", ''),
    NULLIF("work_schedule", ''),
    CASE LOWER(NULLIF("ready_to_relocate", ''))
        WHEN 'true'  THEN TRUE
        WHEN 'false' THEN FALSE
        ELSE NULL
    END,
    CASE LOWER(NULLIF("ready_for_business_trips", ''))
        WHEN 'true'  THEN TRUE
        WHEN 'false' THEN FALSE
        ELSE NULL
    END,
    NULLIF("city", ''),
    CASE LOWER(NULLIF("has_car", ''))
        WHEN 'true'  THEN TRUE
        WHEN 'false' THEN FALSE
        ELSE NULL
    END
FROM candidates_raw;
