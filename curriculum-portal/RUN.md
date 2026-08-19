# RUN.md — Running Curriculum Portal end to end

Four services, started in this order: **database → nlp-engine → backend → frontend**.
Each later service depends on the one(s) before it being up.

## Prerequisites

- Node.js 18+ (native `fetch`/`FormData` are used — no polyfill)
- Python 3.10+
- PostgreSQL 14+ (a local install, or Docker — both covered below)

---

## 1. Database

Create the database and apply the schema:

```bash
cd database
cp .env.example .env
createdb curriculum_portal
psql -d curriculum_portal -f schema.sql
```

**No local Postgres install?** Run one in Docker instead:

```bash
docker run -d --name curriculum-portal-pg \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=curriculum_portal \
  -p 5432:5432 postgres:16-alpine

docker cp database/schema.sql curriculum-portal-pg:/schema.sql
docker exec curriculum-portal-pg psql -U postgres -d curriculum_portal -f /schema.sql
```

> **Windows gotcha:** if you already have a native Postgres service running, it may bind
> `127.0.0.1:5432` while Docker's port mapping binds `0.0.0.0:5432` — both can coexist,
> and `localhost` from Node/Python will resolve to the *native* one, not your container.
> If `backend`/`nlp-engine` report "database does not exist" despite the container looking
> fine, this is almost always why. Fix: map the container to a different host port (e.g.
> `-p 5433:5432`) and point `DATABASE_URL` at that port instead.

Optional — seed `job_skills` from a real O*NET export:

```bash
pip install -r requirements.txt
python import_onet.py --file "Technology Skills.txt"
```

---

## 2. NLP engine (Python + FastAPI)

```bash
cd nlp-engine
cp .env.example .env
python -m venv venv
# Windows: venv\Scripts\activate    |    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`

This service is independent — it doesn't know the backend exists. The backend calls it
over HTTP (see `NLP_ENGINE_URL` below), and only when `USE_MOCK_ANALYSIS=false`.

---

## 3. Backend (Node.js + Express)

```bash
cd backend
cp .env.example .env
npm install
npm run dev
```

Edit `.env` — in particular make sure `DATABASE_URL` points at whichever Postgres you set
up in step 1 (watch for the port-conflict gotcha above).

Verify: `curl http://localhost:4000/api/health` → `{"status":"ok"}`

**Seed two demo institute logins** (used by the frontend's quick-login buttons):

```bash
npm run seed
```

This creates:

| Institute | Email | Password |
|---|---|---|
| Ivy Tech Institute | `demo.ivytech@curriculum.dev` | `DemoPass123!` |
| Metro State College | `demo.metro@curriculum.dev` | `DemoPass123!` |

Safe to re-run — an existing email is skipped, not duplicated.

**Mock vs. real analysis:** `USE_MOCK_ANALYSIS=true` (the `.env.example` default) makes
`POST /upload` return fixed mock data without needing `nlp-engine` running at all — good
for frontend-only work. Set it to `false` once `nlp-engine` (step 2) is up, to get real
skill extraction + job-market matching. See `backend/services/analyzeSubmission.js`.

---

## 4. Frontend (React + Vite)

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`. `/api` requests are proxied to the backend automatically in
dev (see `vite.config.js`) — no CORS setup needed locally.

---

## Walking the full flow

With all four services up (steps 1–4):

1. Open `http://localhost:5173` → redirected to **/login**.
2. Click either demo-account button (or sign up your own institute).
3. You land on **Upload** → drag/drop or browse a `.pdf`/`.docx` syllabus → **Upload &
   Analyze**.
4. On success, click **View full report →**.
5. **Report** page shows the gap-score gauge, NEP-score gauge, matched skills (green),
   missing skills (red).
6. Go to **Dashboard** → your submission appears as a card; click it to return to its
   report.

The JWT session lives in React state only (see `SKILL.md` §5) — refreshing the page logs
you out; log back in with the same demo button or your own credentials.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `POST /api/upload` → 401 | Not logged in, or logged-in session was cleared by a page refresh |
| `POST /api/upload` → 502 "Failed to analyze syllabus" | `USE_MOCK_ANALYSIS=false` but `nlp-engine` isn't running/reachable |
| `GET /api/report/:id` → 404 for a report you just created | You're logged into a different institute than the one that uploaded it |
| Backend can't connect to Postgres | Check the Windows port-conflict gotcha in step 1 |
| `EADDRINUSE` on 4000/8000/5173 | A previous run of that service is still listening — stop it before restarting |
| Frontend shows demo-login buttons but login fails | `npm run seed` hasn't been run against the database this backend is pointed at |
