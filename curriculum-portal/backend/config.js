import 'dotenv/config';

if (!process.env.JWT_SECRET) {
  console.warn(
    'WARNING: JWT_SECRET is not set. Using an insecure default — do not use this outside local dev.'
  );
}

/** Read a positive-integer env var, falling back (with a warning) if it's unusable. */
function readPositiveInt(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) {
    console.warn(`WARNING: ${name}='${raw}' is not a positive integer. Using ${fallback}.`);
    return fallback;
  }
  return value;
}

export const JWT_SECRET = process.env.JWT_SECRET || 'insecure-dev-secret-change-me';
export const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '7d';

// Trailing slashes are stripped so `${NLP_ENGINE_URL}/analyze` can't become
// a double-slashed path if someone sets NLP_ENGINE_URL=http://host:8000/
export const NLP_ENGINE_URL = (process.env.NLP_ENGINE_URL || 'http://localhost:8000').replace(
  /\/+$/,
  ''
);

// Generous by default: a cold nlp-engine loads spaCy + Sentence-BERT before
// it can answer, and embedding a full syllabus against the whole job_skills
// set is seconds of real work. Too short a timeout here turns a slow-but-
// working analysis into a failed upload.
export const NLP_ANALYZE_TIMEOUT_MS = readPositiveInt('NLP_ANALYZE_TIMEOUT_MS', 120_000);

// The health probe must stay cheap — it runs before uploads, so its timeout
// is the delay a user waits to find out the NLP engine is down.
export const NLP_HEALTH_TIMEOUT_MS = readPositiveInt('NLP_HEALTH_TIMEOUT_MS', 3_000);

// How long a health result may be reused before re-probing. Keeps a burst of
// uploads from probing on every request while staying fresh enough that a
// service going down is noticed within seconds.
export const NLP_HEALTH_CACHE_MS = readPositiveInt('NLP_HEALTH_CACHE_MS', 5_000);

// When true (default), POST /api/upload verifies the nlp-engine is up and
// ready *before* accepting a file, so a down NLP service fails fast with a
// clear 503 instead of after a full upload. Set false to skip the pre-flight
// check and let the analyze call itself surface the failure.
export const REQUIRE_NLP_READY = (process.env.REQUIRE_NLP_READY ?? 'true').toLowerCase() !== 'false';

// GET /api/compare returns sample institutes instead of querying the
// database. Defaults to true while the comparison view is being built against
// mock data; set false to run the real query in services/compareInstitutes.js.
// The response always reports which source it used, so a mock payload can't
// be mistaken for live data downstream.
export const COMPARE_USE_MOCK = (process.env.COMPARE_USE_MOCK ?? 'true').toLowerCase() !== 'false';
