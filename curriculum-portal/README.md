# Curriculum Portal

Scaffolding for a syllabus analysis platform: upload a syllabus, extract skills via NLP,
semantically match them against a target skill set, and view the results in a report dashboard.

This is scaffolding only — routes and UI are placeholders with `TODO`s marking where logic
needs to be implemented.

## Structure

```
curriculum-portal/
├── frontend/     React (Vite) app — syllabus upload page + report dashboard page
├── backend/      Node.js + Express API — /upload, /analyze, /report routes
├── nlp-engine/   Python FastAPI service — skill extraction + semantic matching
└── database/     PostgreSQL schema files
```

## Prerequisites

- Node.js 18+
- Python 3.10+
- PostgreSQL 14+

## Setup & running locally

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

Optionally, seed `job_skills` from an O*NET "Technology Skills.txt" export:

```bash
cd database
pip install -r requirements.txt
python import_onet.py --file "Technology Skills.txt"
```

### 2. Backend (Node.js + Express)

```bash
cd backend
cp .env.example .env
npm install
npm run dev
```

Runs on `http://localhost:4000` by default. Exposes `/api/auth/signup`, `/api/auth/login`,
`/api/upload`, `/api/report/:id`, `/api/reports`.

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
uvicorn app.main:app --reload --port 8000
```

Runs on `http://localhost:8000` by default. This service is independent of the Node backend;
the backend calls it over HTTP (see `NLP_ENGINE_URL` in `backend/.env.example`).

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

1. PostgreSQL (must be running and schema applied)
2. `nlp-engine` (FastAPI)
3. `backend` (Express — calls the NLP engine and the database)
4. `frontend` (Vite dev server — calls the backend)

## Status

This is scaffolding only. No upload, extraction, matching, or reporting logic is implemented
yet — see the `TODO` comments throughout each service for what's next.
