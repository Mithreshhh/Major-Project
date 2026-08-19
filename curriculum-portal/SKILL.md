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

---

## 5. Backend — auth, upload, and the mock/real analysis boundary

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

**`analyzeSubmission()` as a mock/real toggle behind `USE_MOCK_ANALYSIS`, not two separate
code paths the caller chooses between:** The task explicitly asked for mock data now with
a clear marker for where the real integration goes later. Rather than just leaving a
comment, the real nlp-engine integration (file upload, response shape adaptation) is
*already implemented* in the same file, gated by one env var — flipping
`USE_MOCK_ANALYSIS=false` is the entire migration, no code changes needed. This was
possible because the real integration already existed from an earlier iteration of
`/upload` (before auth was added) and was preserved rather than deleted.

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

## 7. What was actually verified vs. assumed

Every claim above about "verified in practice" refers to real command execution recorded
in this session — a throwaway Docker Postgres container, both services actually started,
real HTTP requests made with `curl`, actual bcrypt hashes and JWTs inspected. Two things
were explicitly *not* visually verified via a real browser until directly requested:
the initial plain-CSS upload page, and the first pass of the dark-theme UI (which is what
surfaced the `text-decoration` underline bug — a real defect that automated build/API
testing cannot catch, since it's a rendering-only issue). That gap is the reason a
Playwright-driven visual check was added for this revision.
