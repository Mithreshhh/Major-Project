# Curriculum Portal

Scaffolding for a syllabus analysis platform: upload a syllabus, extract skills via NLP,
semantically match them against a target skill set, and view the results in a report dashboard.

## Structure

```
curriculum-portal/
├── frontend/       React (Vite) app — syllabus upload page + report dashboard page
├── backend/        Node.js + Express API — /upload, /analyze, /report, /health routes
├── nlp-engine/     Python FastAPI service — skill extraction + semantic matching
├── database/       PostgreSQL schema + reference-data extract/seed scripts
├── start-all.ps1   Start all three app services with one command (Windows)
└── start-all.sh    Same, for macOS/Linux
```

## Prerequisites

- Node.js 18+
- Python 3.10+
- PostgreSQL 14+

## Setup & running locally

**Shortcut:** after the database is set up (step 1), `.\start-all.ps1 -Install` (Windows)
or `./start-all.sh --install` (macOS/Linux) sets up and starts the other three services in
one command. See [RUN.md](RUN.md) for the full walkthrough — it's the authoritative
run guide; the steps below are the per-service breakdown.

Each service has its own `.env.example` — copy it to `.env` in the same folder and adjust
values as needed before running.

### 1. Database (PostgreSQL)

```bash
cd database
cp .env.example .env
# create the database (name matches POSTGRES_DB in .env.example)
createdb curriculum_portal
# apply the schema
psql -d curriculum_portal -f schema.sql
```

Seed the two reference tables analysis scores syllabi against — `job_skills` is required
(the NLP engine reports itself not-ready without it), `nep_competencies` enables the NEP
score:

```bash
cd database
pip install -r requirements.txt
python import_onet.py --file "Technology Skills.txt"   # job-market skills (O*NET export)
python seed_nep.py                                      # NEP competencies (from the policy PDF)
```

The NEP competency set is derived from Part II (Higher Education) of the NEP 2020 policy
document, extracted by `extract_nep_chapter.py` into
`nlp-engine/data/nep_2020_higher_education.txt`; each competency cites the policy
paragraph it came from.

### 2. Backend (Node.js + Express)

```bash
cd backend
cp .env.example .env
npm install
npm run dev
```

Runs on `http://localhost:4000` by default. Exposes `/api/auth/signup`, `/api/auth/login`,
`/api/upload`, `/api/report/:id`, `/api/reports`, and the health endpoints `/api/health`,
`/api/health/nlp`, `/api/health/full`.

`/api/upload` sends the file to the NLP engine for real analysis, and refuses uploads
while that service is unreachable or still loading its models — check `/api/health/nlp`
first.

Optionally seed two demo institute logins (used by the frontend Login page's quick-login
buttons):

```bash
npm run seed
```

### 3. NLP engine (Python + FastAPI)

```bash
cd nlp-engine
cp .env.example .env
python -m venv venv
# Windows: venv\Scripts\activate | macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --reload --port 8000
```

Runs on `http://localhost:8000` by default. This service is independent of the Node backend;
the backend calls it over HTTP (see `NLP_ENGINE_URL` in `backend/.env.example`).

`GET /health` is a readiness check — it reports whether the NLP models have loaded, the
database is reachable, and the reference tables are seeded. It takes ~10-30s after startup
to report `"ready": true` while spaCy and Sentence-BERT load.

### 4. Frontend (React + Vite)

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Runs on `http://localhost:5173` by default, with `/api` proxied to the backend in dev
(see `frontend/vite.config.js`).

Log in with the demo accounts from `npm run seed` (see above), or sign up your own institute.
The JWT session token is kept in memory only (React context) — it's cleared on refresh.

## Running order

Start them in this order so each dependency is available when the next one needs it:

1. PostgreSQL (must be running, schema applied, reference tables seeded)
2. `nlp-engine` (FastAPI)
3. `backend` (Express — calls the NLP engine and the database)
4. `frontend` (Vite dev server — calls the backend)

`start-all.ps1` / `start-all.sh` does steps 2-4 in this order for you, waiting for each
service to report healthy before starting the next.

## Status

The end-to-end flow works: upload a `.pdf`/`.docx` syllabus, and it's sent to the NLP
engine for spaCy-based skill extraction and Sentence-BERT matching against job-market
skills and NEP competencies, with the result stored in `gap_reports`/`reports` and
rendered on the report page.

Known gaps: `POST /api/analyze` (analyze-by-id) is still a `501` stub, `extracted_skills`
rows aren't persisted to their own table (the full payload lives in `reports.summary`
JSONB), and NEP scoring uses a binary similarity threshold that reports 0% for a purely
technical syllabus — a correct but uninformative answer. See the graded-score
recommendation in `SKILL.md` §4. Remaining `TODO` comments mark the rest.
