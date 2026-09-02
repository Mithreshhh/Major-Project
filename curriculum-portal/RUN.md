# RUN.md — Running Curriculum Portal end to end

Four services, started in this order: **database → nlp-engine → backend → frontend**.
Each later service depends on the one(s) before it being up.

## Prerequisites

- Node.js 18+ (native `fetch`/`FormData` are used — no polyfill)
- Python 3.10+
- PostgreSQL 14+ (a local install, or Docker — both covered below)

---

## Quickstart — all three app services in one command

Set up the database first (step 1 below — it has its own lifecycle and isn't
started by the script), then:

```powershell
# Windows / PowerShell
.\start-all.ps1 -Install     # first run only: venv, pip, spaCy model, npm install
.\start-all.ps1              # every run after that
```

```bash
# macOS / Linux
./start-all.sh --install     # first run only
./start-all.sh               # every run after that
```

This starts **nlp-engine → backend → frontend** in dependency order, waiting for
each to report healthy before starting the next, and prints where everything is
listening. Ctrl+C once stops all three.

Because the nlp-engine loads spaCy and Sentence-BERT before it can answer, the
first start takes ~10-30 seconds (and longer the very first time, when the
models are downloaded). The script shows what it's waiting on rather than
failing.

The rest of this file is the manual, service-by-service version — useful when
you want to run just one service, or when the script reports a problem.

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

**Seed the two reference tables.** These are not optional any more — analysis
scores a syllabus *against* them, so `/analyze` refuses to run without
`job_skills`, and `nep_score` comes back `null` without `nep_competencies`:

```bash
pip install -r requirements.txt

# Job-market skills, from a real O*NET export.
# Required — the nlp-engine reports itself "not ready" while this is empty.
# Download the tab-delimited O*NET database from https://www.onetcenter.org/database.html
# and put these files in database/onet_raw/ (gitignored):
#   Technology Skills.txt   (required)  — concrete tools: Python, Git, AWS
#   Skills.txt              (optional)  — worker skills: Programming, Critical Thinking
#   Occupation Data.txt     (optional)  — resolves SOC codes for Skills.txt
python fetch_and_import_onet.py --dry-run    # preview first — no DB writes
python fetch_and_import_onet.py

# NEP competency reference set, derived from the policy document itself.
# Safe to re-run; use --truncate to replace an edited set.
python seed_nep.py
```

The NEP competencies come from **Part II (Higher Education), sections 9–19 of NEP 2020**,
extracted from the official PDF at the repo root:

```bash
python extract_nep_chapter.py     # NEP_Final_English_0.pdf -> nlp-engine/data/nep_2020_higher_education.txt
```

That text file is committed, so you only need to re-run the extractor if you replace the
PDF. Every competency in `seed_nep.py` cites the policy paragraph it came from, and
`seed_nep.py` verifies those citations against the extracted text each time it runs —
a mismatch is reported rather than silently seeded.

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

Verify: `curl http://localhost:8000/health`

`/health` is a **readiness** check, not just a ping. It reports whether the NLP
models have finished loading, whether the database is reachable, and whether the
reference tables are seeded:

```json
{
  "status": "ok",
  "ready": true,
  "checks": {
    "models":           { "status": "ok" },
    "database":         { "status": "ok" },
    "job_skills":       { "status": "ok", "count": 412 },
    "nep_competencies": { "status": "ok", "count": 20 }
  }
}
```

`ready` is false for the first ~10-30 seconds while spaCy and Sentence-BERT
load (`models: "loading"`) — that's normal, and the backend refuses uploads
until it flips true. If a check stays wrong, the `status`/`detail` on that check
names the fix. Set `WARM_MODELS_ON_STARTUP=false` to skip preloading and load
models lazily on first request instead.

Note `nep_competencies: "empty"` is *degraded, not unready*: analysis still runs
and returns a gap score, just with a `null` NEP score.

This service is independent — it doesn't know the backend exists. The backend
calls it over HTTP (see `NLP_ENGINE_URL` below).

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

**Health endpoints:**

| Endpoint | Answers |
|---|---|
| `GET /api/health` | Is the backend up? (no dependencies touched) |
| `GET /api/health/nlp` | Is the NLP engine up and able to analyze? `200` ready, `503` not |
| `GET /api/health/full` | Backend + Postgres + NLP engine in one call |

`GET /api/health/nlp` is the one to check before uploading — it's the same check
`POST /api/upload` runs internally.

**Uploads are gated on NLP readiness.** `POST /api/upload` health-checks the NLP
engine *before* reading the uploaded file, so a down or still-warming service
costs you an immediate `503` instead of a full upload that then fails. Set
`REQUIRE_NLP_READY=false` to skip the pre-flight and let the analyze call itself
surface the failure.

**Timeouts** are configurable in `.env` — `NLP_ANALYZE_TIMEOUT_MS` (default
120000, generous because a cold engine loads models first) and
`NLP_HEALTH_TIMEOUT_MS` (default 3000, kept short since it runs before uploads).

There is no mock-analysis mode: `POST /api/upload` always calls the real
nlp-engine. See `backend/services/analyzeSubmission.js` and `nlpClient.js`.

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

With all four services up (steps 1–4, or the Quickstart script). Confirm
everything is actually wired up first:

```bash
curl http://localhost:4000/api/health/full     # expect "ready": true
```

Then: 

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

Upload failures carry a `code` and a `details` field naming the actual cause —
check those first. The status code tells you whose problem it is:

| Status | `code` | Meaning |
|---|---|---|
| 503 | *(pre-flight)* | NLP engine down or not ready — uploads paused before the file was read |
| 503 | `NLP_UNAVAILABLE` | NLP engine is up, but its database or seed data isn't |
| 504 | `NLP_TIMEOUT` | NLP engine accepted the request but didn't answer in time |
| 422 | `NLP_REJECTED_FILE` | Your file — wrong type, empty, or no extractable skills |
| 502 | `NLP_ERROR` / `NLP_BAD_RESPONSE` | NLP engine failed internally or returned an unusable payload |

| Symptom | Likely cause |
|---|---|
| `POST /api/upload` → 401 | Not logged in, or the session was cleared by a page refresh |
| `POST /api/upload` → 503 "uploads are paused" | `nlp-engine` isn't running, or is still loading models. Check `GET /api/health/nlp` |
| `/health` shows `job_skills: empty` | `fetch_and_import_onet.py` hasn't been run — `/analyze` can't score anything |
| O*NET import reports "no O*NET occupation matched" | That job title doesn't exist in the SOC taxonomy, or was renamed in this release — edit `TARGET_OCCUPATIONS` |
| Report shows a blank NEP gauge | `nep_competencies` is empty — run `python database/seed_nep.py` |
| `/health` shows `database: error` but the backend works fine | The two services point at **different** Postgres instances — compare `DATABASE_URL` in `backend/.env` and `nlp-engine/.env`, and see the Windows port gotcha in step 1 |
| `/health` shows `models: error` | The spaCy model isn't installed — `python -m spacy download en_core_web_sm` |
| First upload after startup times out | Models were still loading. Wait for `ready: true`, or raise `NLP_ANALYZE_TIMEOUT_MS` |
| `GET /api/report/:id` → 404 for a report you just created | You're logged into a different institute than the one that uploaded it |
| Backend can't connect to Postgres | Check the Windows port-conflict gotcha in step 1 |
| `EADDRINUSE` on 4000/8000/5173 | A previous run of that service is still listening — stop it before restarting |
| Frontend shows demo-login buttons but login fails | `npm run seed` hasn't been run against the database this backend is pointed at |
