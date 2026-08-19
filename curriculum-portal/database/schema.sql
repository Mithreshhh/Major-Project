-- Curriculum Portal database schema
-- TODO: refine columns/constraints once upload, analyze, and report flows are implemented
-- TODO: add migrations tooling (e.g. node-pg-migrate, Flyway) instead of hand-run SQL

CREATE TABLE IF NOT EXISTS institutes (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    -- TODO: enforce uniqueness/format once institute onboarding flow exists (e.g. AICTE/UGC code)
    code TEXT,
    location TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Institute staff accounts (see backend/routes/auth.js)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    institute_id INTEGER REFERENCES institutes(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS syllabi (
    id SERIAL PRIMARY KEY,
    institute_id INTEGER REFERENCES institutes(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    -- TODO: store file location (path/S3 key) once storage strategy is decided
    file_path TEXT,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS extracted_skills (
    id SERIAL PRIMARY KEY,
    syllabus_id INTEGER NOT NULL REFERENCES syllabi(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    -- TODO: add confidence score, source span, etc. once extraction logic exists
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Industry-demand skills, sourced from O*NET Technology Skills data (see import_onet.py)
CREATE TABLE IF NOT EXISTS job_skills (
    id SERIAL PRIMARY KEY,
    occupation_title TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    -- e.g. "Hot Technology" / "In Demand" category from O*NET, or a custom grouping
    skill_category TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (occupation_title, skill_name)
);

-- National Education Policy (NEP) competency reference set, matched against syllabi
CREATE TABLE IF NOT EXISTS nep_competencies (
    id SERIAL PRIMARY KEY,
    competency_name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    syllabus_id INTEGER NOT NULL REFERENCES syllabi(id) ON DELETE CASCADE,
    -- TODO: define report structure (JSONB summary, gap analysis, match scores, etc.)
    summary JSONB,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Computed gap analysis: how well a syllabus matches job_skills demand and nep_competencies
CREATE TABLE IF NOT EXISTS gap_reports (
    id SERIAL PRIMARY KEY,
    syllabus_id INTEGER NOT NULL REFERENCES syllabi(id) ON DELETE CASCADE,
    -- TODO: define scoring scale/formula (e.g. 0-100) once the analysis engine is implemented
    gap_score NUMERIC(5, 2),
    nep_score NUMERIC(5, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_institute_id ON users(institute_id);
CREATE INDEX IF NOT EXISTS idx_syllabi_institute_id ON syllabi(institute_id);
CREATE INDEX IF NOT EXISTS idx_extracted_skills_syllabus_id ON extracted_skills(syllabus_id);
CREATE INDEX IF NOT EXISTS idx_job_skills_occupation_title ON job_skills(occupation_title);
CREATE INDEX IF NOT EXISTS idx_gap_reports_syllabus_id ON gap_reports(syllabus_id);
