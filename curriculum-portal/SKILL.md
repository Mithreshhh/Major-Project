# SKILL.md — What was built, and why

This documents every non-trivial technical decision made across `curriculum-portal`,
organized by service. For each decision: what it is, what else was considered, and why
that alternative lost. Setup/run instructions live in `RUN.md`, not here.

---

## 1. Overall architecture — 4 separate services, not a monolith

**What:** `frontend` (React/Vite), `backend` (Node/Express), `nlp-engine` (Python/FastAPI),
`database` (Postgres) as four independently runnable services communicating over HTTP.

**Alternatives considered:**
- A single Node.js monolith doing everything, including NLP in JS.
- A single Python monolith (Django/Flask) serving the frontend too.

**Why this split:** The NLP work (spaCy, sentence-transformers/PyTorch) has no mature
equivalent in the Node ecosystem — doing skill extraction and semantic matching in
JavaScript would mean either shelling out to Python anyway or using far weaker tooling.
Splitting the NLP work into its own Python service keeps each language doing what it's
actually good at, and lets the NLP service's heavy ML dependencies (PyTorch et al.) stay
isolated from the request-handling backend, which only needs to be fast and lightweight.
The cost is an extra network hop (`backend` → `nlp-engine`) and two runtimes to keep
running locally — judged worth it over bolting ML tooling onto Node or making the
request-handling API pay Python's dependency weight.

---

## 2. Database — schema shape and a few explicit denormalization choices

**What:** `institutes` → `users` → `syllabi` → `gap_reports` / `reports`, plus two
reference tables (`job_skills`, `nep_competencies`) populated independently.

**Two tables for one report — `gap_reports` (scores) + `reports` (JSONB detail):**
The task spec fixed `gap_reports`' columns to `(syllabus_id, gap_score, nep_score,
created_at)` — no room for the full matched/missing skill lists. Rather than widen that
table (which wasn't asked for) or lose the detail entirely, the full analysis payload is
stored as JSONB in the pre-existing `reports.summary` column, keyed by the same
`syllabus_id`. `GET /report/:id` joins both. This keeps the numeric scores in a queryable,
typed table (useful for future "average gap score across institute" style queries) while
keeping the variable-shape skill lists out of the relational schema, where they'd need
either a join table or JSON anyway.

**`job_skills` uses a composite unique constraint, not a synthetic key on skill name
alone:** `UNIQUE (occupation_title, skill_name)` — the same skill (e.g. "Python") is
legitimately relevant to multiple occupations with different `skill_category` framing.
Deduplicating only on `skill_name` would have silently dropped rows during O*NET import.

**Institute-scoped access via `institute_id` on `syllabi`, not a join table:** A syllabus
belongs to exactly one institute, so a direct foreign key is sufficient — a many-to-many
join table would be unjustified complexity for a relationship that's actually one-to-many.

---

## 3. `database/import_onet.py` — plain `csv` module, not pandas

**What:** O*NET's tab-delimited "Technology Skills.txt" is parsed with Python's built-in
`csv.DictReader`, filtered to five CS-relevant occupations by case-insensitive substring
match, deduped, and bulk-loaded via `psycopg2.extras.execute_values` with
`ON CONFLICT DO NOTHING`.

**Why substring match, not exact equality, for occupation filtering:** O*NET's occupation
titles shift between taxonomy versions (e.g. "Database Administrators" vs "Database
Administrators and Architects" in newer releases). Exact-match filtering would silently
drop an entire occupation the moment O*NET updates its titles; substring match is robust
to that drift at the cost of being very slightly more permissive.

**Why `csv` instead of `pandas`:** The transformation is a straight filter + rename, no
joins, no aggregation, no missing-data imputation — pandas would add a large dependency
for no functional benefit here. `csv.DictReader` plus a generator function does the same
job with zero extra install weight and a smaller surface area to get wrong.

**Why `ON CONFLICT DO NOTHING` instead of upsert:** Re-running the import (e.g. after
O*NET publishes an update) should be idempotent without needing to diff old vs. new rows
row-by-row in application code — Postgres already does that check at the constraint level,
faster and with no race condition between the "does it exist" read and the insert.

---

## 4. NLP engine — spaCy for extraction, Sentence-BERT for matching

**`skill_extraction.py` — spaCy noun chunks + a small NER label allowlist, not an LLM
call or a fixed keyword list:**

- *Considered: a hardcoded skill keyword list (e.g. "Python", "SQL", "React", …).*
  Rejected — it only ever finds skills the list's author already knew about, and syllabi
  constantly introduce new tools/frameworks a static list can't anticipate.
- *Considered: calling an LLM to extract skills.* Rejected for this stage — it's slower,
  costs money per request, and is nondeterministic, which makes the extraction step hard
  to unit-test with a fixed expected output. spaCy's noun-chunk parser is deterministic,
  fast (no network call), and "skills/topics" in a syllabus are overwhelmingly noun
  phrases ("object-oriented programming", "relational database design") — a good fit for
  a grammatical-structure-based approach rather than a semantic one.
- **Noise removal was the actual hard part, not extraction.** The first self-test run
  (documented in the conversation, not just asserted) surfaced three real bugs: raw
  newlines from PDF/DOCX text breaking POS-based determiner trimming, spaCy occasionally
  merging a comma-separated list into one noun chunk ("object-oriented programming,
  relational database design" as a single span), and generic academic filler ("the
  fundamentals", "this course", "strong understanding") passing through untouched. Each
  was fixed based on actually running the code against a sample paragraph, not guessed at
  — see the whitespace-normalization step, the comma-split on noun chunks, and the
  `GENERIC_NOISE_WORDS` tail-word check (deliberately only applied to ≤2-word phrases so
  it doesn't eat legitimate phrases like "software engineering principles").

**`matching_engine.py` — `sentence-transformers` with `all-MiniLM-L6-v2`, not TF-IDF/
Jaccard or a larger embedding model:**

- *Considered: exact/fuzzy string matching (Jaccard, Levenshtein) between skill phrases.*
  Rejected — it can't see that "ML" and "machine learning" or "Node.js" and "backend
  JavaScript development" are related; syllabus phrasing and job-posting phrasing rarely
  match verbatim, which is the entire problem this feature exists to solve.
  Semantic-embedding similarity was necessary, not optional, for job-market gap analysis
  to mean anything.
- *Considered: a larger model (e.g. `all-mpnet-base-v2`) for higher-fidelity embeddings.*
  Rejected for this stage — MiniLM is ~5x smaller and faster with a small accuracy
  tradeoff; for short 2-6 word phrases (not full sentences/paragraphs) the fidelity gap
  narrows further, so the speed/size win dominates. This is an easy dial to turn later if
  matching quality proves insufficient in practice.
- **0.6 similarity threshold was picked empirically, not guessed.** The self-test (run
  live, results included in the conversation) showed near-identical phrases scoring
  ≥0.9-1.0, a real paraphrase ("Python" vs "Python programming") at 0.907, and unrelated
  skills (Kubernetes, React) sitting at 0.03-0.2 against an unrelated syllabus. 0.6 sits
  cleanly in the gap between "genuinely related" and "coincidentally similar."
- **Gap score is job-skills-first, not curriculum-first:** `compute_gap_analysis` iterates
  over job-market skills, finding each one's best syllabus match — not the other way
  around. This makes the gap score meaningfully "% of what the job market wants that this
  syllabus doesn't teach," rather than "% of what this syllabus teaches that's not
  job-relevant" (a different, less useful question for this product).

**`/analyze` endpoint — synchronous request/response, not a job queue:** Given the current
scale (one syllabus at a time, sub-few-second model inference on short text), a queue
would add operational complexity (worker process, job status polling, a message broker)
for no real benefit yet. Worth revisiting if syllabi start requiring long-running batch
analysis.

**NEP scoring reuses the same matcher, inverted — `compute_nep_alignment()` wraps
`compute_gap_analysis()`:** `nep_score` is the percentage of NEP competencies the
syllabus *covers* (higher is better), where `gap_score` is the percentage of job skills
it *misses* (higher is worse). Same embeddings, same threshold, opposite polarity — so
the two numbers are computed by one code path rather than two implementations that could
drift. The polarity flip is what the frontend gauge's existing `invert` flag was already
built for.

**An unseeded `nep_competencies` table yields `null`, not `0` or `100`:** Scoring a
syllabus against an empty competency set is arithmetically "0 missing out of 0", which
`compute_gap_analysis()` would report as a 0% gap — i.e. a perfect 100% NEP score for a
table with nothing in it. `compute_nep_alignment()` intercepts that case and returns
`None`, which becomes SQL `NULL` in `gap_reports.nep_score`. "We didn't measure this" and
"we measured this and it's perfect" must not look the same in the database.

**NEP failures degrade instead of failing the request:** `/analyze` returns a gap score
even if NEP scoring throws or the table is empty. The job-market gap analysis is the
endpoint's reason to exist and is the expensive part; losing the whole response over a
secondary signal would trade the caller's main result for a null they'd have tolerated.

**NEP competencies are embedded by name alone, not name + description** — decided by
measurement, not intuition. The obvious improvement was to embed the richer
`"{name}. {description}"` text from the seed data. Tested against a real document, it
made matching *worse* (top-5 similarities dropped from 0.617/0.612/0.604/0.504/0.451 to
0.557/0.541/0.491/0.469/0.418, and the score fell from 15% to 0%): a long descriptive
sentence dilutes the embedding when the other side is a 2-4 word noun phrase. The
`description` column is retained for display purposes, not matching.

**Known limitation — NEP scores read low, and the 0.6 threshold is the reason.** That
threshold was tuned (§ above) on job-market skills, where both sides are concrete noun
phrases. NEP competencies are abstract capability statements ("Critical thinking and
problem solving") being compared against concrete syllabus topics, and the abstraction
gap costs real similarity: on a measured sample, genuine matches landed just over the
line (0.617 "Vocational skills and hands-on experience" ↔ "hands-on experience", 0.612
"Computational thinking" ↔ "core computer science subjects") while plausible ones fell
short (0.357 "Critical thinking and problem solving" against a CS document). Dropping the
threshold to 0.45 admits as much noise as signal (0.451 "Creativity and innovation" ↔
"Institution Innovation Council" is a name collision, not a competency match). Left at
0.6 deliberately: a separate, lower NEP threshold is defensible but shouldn't be picked
without evaluation data, and inventing one to make the gauge look better would be tuning
for appearance.

**Models are preloaded at startup in a background thread, not lazily on first request:**
Loading spaCy + Sentence-BERT takes ~10-30s (measured: 12s warm). Lazily, that cost lands
on whoever uploads first, looking indistinguishable from a hang. Warming in a daemon
thread from the FastAPI lifespan hook lets uvicorn bind its port immediately — so
`/health` is answerable *during* warmup and can report `models: "loading"` — while the
backend simply refuses uploads until it flips to ready. `WARM_MODELS_ON_STARTUP=false`
restores lazy loading.

**`/health` returns 200 even when not ready, with readiness in the body:** The convention
would be 503 for "up but not ready". Rejected here because the caller that matters most
is the backend, and it needs to tell "the NLP engine isn't running" (connection refused)
apart from "it's up and loading models" — two states that both produce a non-200 under
the conventional design, but call for different messages. Reaching the handler at all is
the liveness answer; `ready` plus per-dependency `checks` carries the rest. The backend's
own `/api/health/nlp` *does* use 503, because there the caller is a human or a probe
script that wants to act on the status code alone.

---

## 5. Backend — auth, upload, and the nlp-engine integration

**bcrypt (native) over bcryptjs (pure JS):** The user's request named `bcrypt` explicitly.
It was verified to actually install and load its native binding cleanly in this
environment before committing to it (a real risk on Windows without build tools) — if
that had failed, `bcryptjs` was the fallback, since it's a drop-in API-compatible
alternative with no native compilation step.

**JWT stored in the client's memory only, not `localStorage`/cookies:** This was an
explicit requirement, not a default choice — and it's a reasonable one: `localStorage` is
readable by any script on the page (XSS risk), and using it would have been the "easy"
choice that trades security for persistence-across-refresh convenience. The tradeoff
accepted here is that refreshing the page logs the user out; for a v1/demo-stage app
that's a reasonable price for not persisting a bearer token in a location that JS-injected
attacks can read.

**Native `fetch`/`FormData`/`Blob` for the backend→nlp-engine call, not `axios` or
`node-fetch`:** Verified Node 24 is available in this environment, where these are stable
globals — adding a dependency (`axios`, `form-data`) for functionality already built into
the runtime would be unjustified weight. This does mean the project implicitly requires
Node ≥18 (where `fetch`/`FormData` first landed as globals); documented via `engines` in
`package.json`.

**`USE_MOCK_ANALYSIS` removed entirely, not left as a fallback:** `analyzeSubmission()`
originally returned fixed mock data behind an env flag, with the real integration
implemented alongside it. Now that the real call is the only path, the flag is gone
rather than kept as a "degrade to mock if the NLP engine is down" escape hatch. Mock
data that silently reaches `gap_reports` is worse than a failed upload: a stored 72%
gap score is indistinguishable from a real one once it's in the table, and every
consumer downstream (dashboard, report page, any future analytics) would treat it as
genuine. An upload that fails loudly with a 503 is recoverable; a database full of
plausible fiction is not.

**Talking to the nlp-engine lives in `services/nlpClient.js`, not inline in
`analyzeSubmission()`:** Three separate concerns needed to share it — the upload route's
pre-flight check, the analysis call itself, and the `/api/health/nlp` endpoint. Keeping
timeouts, error classification, and the health-result cache in one module means those
three agree by construction. `analyzeSubmission()` is left as what it says it is: the
adapter from the engine's `snake_case` response to this app's `camelCase` shape.

**Failures are classified by `code`, not collapsed into one 502:** The original code
returned 502 for every analysis failure. But "the NLP service is down" (503, retry
later), "it didn't answer in time" (504), and "your PDF has no extractable text" (422)
are three different answers, and only the last is the user's to act on. Each
`NlpServiceError` carries a code that maps to a status and a user-facing headline, so
the upload page can say something true. All five paths were verified against a stub
engine rather than reasoned about — see §7.

**Uploads are gated on an NLP health check that runs *before* multer reads the body:**
The check sits in the route handler ahead of `upload.single()`, so when the engine is
down the request is rejected without a 10MB file ever being written to disk. This
matters most in the normal case, not the pathological one: the engine takes ~10-30s to
load its models at startup, and without the gate every upload in that window would
upload fully, then fail. Health results are cached for a few seconds
(`NLP_HEALTH_CACHE_MS`) so a burst of uploads doesn't probe once per request, and the
cache is invalidated the moment an analyze call fails — a stale "healthy" belief is the
one thing the cache must never outlive.

**Two timeouts, not one:** `NLP_ANALYZE_TIMEOUT_MS` defaults to 120s and
`NLP_HEALTH_TIMEOUT_MS` to 3s, because they bound opposite risks. The analyze timeout
guards against a *slow but working* engine — set it too low and a cold-start model load
turns into a failed upload. The health timeout is paid before every upload, so it's the
delay a user sits through to learn the service is down; that one wants to be short. A
single shared value would have to be wrong for one of them.

**`GET /report/:id` returns 404 for another institute's report, not 403:** A 403 confirms
"this resource exists but isn't yours," which leaks information (report ID enumeration
reveals how many reports other institutes have). 404 makes an unauthorized report
indistinguishable from a nonexistent one. Verified in practice (turn 6): logged in as a
second seeded institute, requested the first institute's report ID, got 404 with an empty
`/reports` list — not an assumption, an observed result.

**Transactional signup (institute + user insert in one `BEGIN`/`COMMIT`):** A signup
creates two rows across two tables. Without a transaction, a mid-request crash after the
institute insert but before the user insert would leave an orphaned institute with no
owner. `pool.connect()` + explicit transaction control (rather than two independent
`pool.query()` calls) closes that window.

---

## 6. Frontend — state, styling, and visualization choices

**React Context for auth state, not Redux/Zustand/Jotai:** The entire global state
surface is `{ token, user }` with two mutating actions (`login`, `logout`). A state
management library earns its complexity budget once there's cross-cutting state with many
independent slices, derived selectors, or complex update logic — none of which applies
here. `useState` + `createContext` is the smaller, equally correct tool for this shape of
problem; reaching for Redux here would be complexity added for its own sake.

**Plain CSS (per-page files + one shared `theme.css`), not Tailwind or a component
library:** A utility-class framework (Tailwind) or prebuilt component kit (MUI, Chakra)
trades control over the exact visual language for speed — reasonable for many apps, but
this task explicitly asked for a distinctive, "blow the mind" visual identity (custom
gradient system, animated gauges, glass panels), which is easier to get exactly right with
direct CSS than by fighting a utility framework's defaults or a component library's
built-in theming assumptions. The cost is more CSS to hand-write and maintain; accepted
because visual distinctiveness was the explicit goal.

**Hand-rolled SVG gauge (`GapScoreGauge.jsx`), not a charting library
(Chart.js/Recharts/Nivo):** A circular progress ring is ~40 lines of SVG plus a CSS
transition on `stroke-dashoffset` — pulling in a full charting library for one visual
primitive would be a large dependency for a narrow use. It also gave direct control over
the exact animation feel (`requestAnimationFrame`-triggered transition on mount) and the
color-by-threshold logic, which a general-purpose charting library would have made more
indirect to express.

**`apiRequest()` as a small hand-written `fetch` wrapper, not a data-fetching library
(React Query/SWR):** The app has no caching, background refetch, or optimistic-update
requirements — every fetch happens once per page visit in a `useEffect`. A data-fetching
library's core value (cache invalidation, stale-while-revalidate, request dedup) isn't
exercised by this app's actual usage pattern, so it would be dependency weight without a
matching benefit. Worth reconsidering if the dashboard grows real-time or polling needs.

**Vite's dev proxy (`/api` → `localhost:4000`) instead of a `VITE_API_BASE_URL` env
var at request time:** `frontend/.env.example` documents `VITE_API_BASE_URL` for
production builds, but in dev, the proxy avoids CORS entirely (same-origin from the
browser's perspective) and keeps every fetch call as a plain relative path
(`/api/...`) that works unmodified whether proxied in dev or reverse-proxied in
production.

---

## 7. Startup scripts — `start-all.ps1` / `start-all.sh`

**Shell scripts, not a root `package.json` with `concurrently`:** The npm approach is the
common one, but it would add a fourth `node_modules` at the repo root and a dependency,
purely to launch processes — and it still couldn't do the part that actually matters
here: creating a Python venv, installing pip requirements, or downloading the spaCy
model. A script that can only start two of the three services isn't the "one command" the
task asked for. Two hand-written scripts have no install step of their own and can drive
Python and Node equally.

**Both a PowerShell and a bash version, rather than one cross-platform runner:** The
development environment is Windows, so PowerShell is the primary target; the differences
that matter (`venv\Scripts\python.exe` vs `venv/bin/python`, `taskkill /T` vs signals,
`/dev/tcp` vs `System.Net.Sockets.TcpClient`) are exactly the ones a shared abstraction
would have to paper over. Two idiomatic scripts are shorter and more debuggable than one
that's awkward on both platforms.

**Services start sequentially, gated on health, not all at once:** Launching all three in
parallel is faster and was the first instinct — but the failure it produces is a frontend
that loads fine against a backend whose NLP engine is still warming, which surfaces as a
confusing failed upload rather than a startup error. Waiting on each service's health
endpoint makes startup order a property of the script rather than something the user has
to get right. `-NoHealthWait` / `--no-health-wait` opts out.

**Postgres is deliberately *not* started by the script:** It's a system service or a
Docker container with a lifecycle that outlives a dev session, and it may already be
running with data in it. Starting or (worse) initializing it from a convenience script
risks acting on the wrong instance. Instead the nlp-engine's readiness check reports
whether the database is reachable and seeded, so a database problem shows up as a named
check rather than a silent hang.

**Services are launched via their real binaries (`node`, `node vite.js`), not
`npm run dev`:** `npm` on Windows wraps the real process in a `cmd.exe` shell, so killing
the npm process can orphan the server it spawned — which then holds port 4000 and makes
the next run fail with `EADDRINUSE`. Invoking `node` directly makes the tracked PID the
actual server, so Ctrl+C cleanup is reliable. The scripts also pre-check that 8000/4000/
5173 are free and refuse to start rather than half-starting into that error.

---

## 8. What was actually verified vs. assumed

Every claim above about "verified in practice" refers to real command execution recorded
in this session — a throwaway Docker Postgres container, both services actually started,
real HTTP requests made with `curl`, actual bcrypt hashes and JWTs inspected. Two things
were explicitly *not* visually verified via a real browser until directly requested:
the initial plain-CSS upload page, and the first pass of the dark-theme UI (which is what
surfaced the `text-decoration` underline bug — a real defect that automated build/API
testing cannot catch, since it's a rendering-only issue). That gap is the reason a
Playwright-driven visual check was added for this revision.

**The nlp-engine integration was verified the same way.** Every failure path was
exercised against a stub nlp-engine that could be put into each failure mode on demand,
because the interesting cases (timeout, malformed payload, dependency missing) are ones a
correctly-working service never produces. Confirmed by observation, not inspection: 503
pre-flight rejection with the engine stopped and with it reporting `ready: false`, 504 on
a `/analyze` that never answers, 422 on an upstream file rejection, 502 on both an
upstream 500 and an unparseable payload, and 201 storing real values on success.

The real engine was then run end to end — spaCy and Sentence-BERT actually loaded, a real
`.docx` extracted, matched, scored, written to `gap_reports`, and read back through
`GET /api/report/:id`. Two findings came out of running it rather than reasoning about
it: the ~12-second window where `/health` reports `models: "loading"` (which is the whole
justification for the upload gate), and the NEP threshold measurements in §4 that
overturned the assumption that richer competency text would match better.

Test artifacts were removed afterwards — the syllabi/gap_reports rows and uploaded files
created during verification, and a temporary `job_skills` set inserted to make the real
end-to-end run possible. The `nep_competencies` seed was kept, since it's a deliverable
rather than test data.
