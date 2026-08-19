/**
 * HTTP client for the nlp-engine FastAPI service.
 *
 * Everything that knows the NLP engine speaks HTTP lives here: timeouts,
 * failure classification, and the health probe. Callers get either a parsed
 * result or an NlpServiceError carrying a `code` they can map to a status —
 * they never see fetch/AbortSignal details.
 *
 * Uses native fetch/FormData/Blob (Node 18+, see package.json engines).
 */
import fs from 'node:fs/promises';

import {
  NLP_ANALYZE_TIMEOUT_MS,
  NLP_ENGINE_URL,
  NLP_HEALTH_CACHE_MS,
  NLP_HEALTH_TIMEOUT_MS,
} from '../config.js';

/**
 * A failure talking to (or reported by) the nlp-engine.
 *
 * `code` distinguishes failure kinds that deserve different HTTP responses:
 *
 *   NLP_UNREACHABLE   the service isn't accepting connections    -> 503
 *   NLP_NOT_READY     it's up but can't analyze yet              -> 503
 *   NLP_UNAVAILABLE   its own dependency failed (db, seed data)  -> 503
 *   NLP_TIMEOUT       it accepted the request but didn't answer  -> 504
 *   NLP_REJECTED_FILE it rejected this file (4xx)                -> 422
 *   NLP_BAD_RESPONSE  it answered with an unusable payload       -> 502
 *   NLP_ERROR         it failed internally (5xx)                 -> 502
 */
export class NlpServiceError extends Error {
  constructor(message, { code, cause } = {}) {
    super(message, { cause });
    this.name = 'NlpServiceError';
    this.code = code || 'NLP_ERROR';
  }
}

const STATUS_BY_CODE = {
  NLP_UNREACHABLE: 503,
  NLP_NOT_READY: 503,
  NLP_UNAVAILABLE: 503,
  NLP_TIMEOUT: 504,
  NLP_REJECTED_FILE: 422,
  NLP_BAD_RESPONSE: 502,
  NLP_ERROR: 502,
};

/** Map an NlpServiceError (or anything else) to the status to return to our client. */
export function httpStatusForNlpError(err) {
  return STATUS_BY_CODE[err?.code] || 502;
}

/**
 * fetch() against the NLP engine with a hard timeout, translating transport
 * failures into NlpServiceError. Non-2xx responses are returned as-is for the
 * caller to interpret — only *reaching* the service is handled here.
 */
async function requestNlp(path, { method = 'GET', body, timeoutMs } = {}) {
  try {
    return await fetch(`${NLP_ENGINE_URL}${path}`, {
      method,
      body,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (err) {
    // AbortSignal.timeout() rejects with a TimeoutError; a manual abort or an
    // older runtime surfaces AbortError. Both mean "we gave up waiting".
    if (err?.name === 'TimeoutError' || err?.name === 'AbortError') {
      throw new NlpServiceError(
        `The NLP engine did not respond within ${timeoutMs}ms. It may be starting up, loading models, or overloaded.`,
        { code: 'NLP_TIMEOUT', cause: err }
      );
    }
    throw new NlpServiceError(
      `Could not reach the NLP engine at ${NLP_ENGINE_URL}. Is it running? (${err.message})`,
      { code: 'NLP_UNREACHABLE', cause: err }
    );
  }
}

/** Pull the most useful error text out of a non-2xx nlp-engine response. */
async function readErrorDetail(response) {
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') return body.detail;
    if (body?.detail) return JSON.stringify(body.detail);
    return JSON.stringify(body);
  } catch {
    try {
      return (await response.text()).slice(0, 500);
    } catch {
      return `HTTP ${response.status}`;
    }
  }
}

// Cached health result, so a burst of uploads doesn't probe once per request.
let cachedHealth = null; // { checkedAt: number, result: object }

/**
 * Probe the nlp-engine's /health endpoint.
 *
 * Never throws: a health check that fails *is* the answer. Returns
 *   { reachable, ready, status, checks, error, checkedAt }
 * where `reachable` means we got an HTTP response at all and `ready` means
 * the engine reports it can actually analyze a syllabus right now.
 *
 * @param {object}  [options]
 * @param {number}  [options.maxAgeMs] Reuse a cached result younger than this.
 *                                     Pass 0 to force a fresh probe.
 */
export async function checkNlpHealth({ maxAgeMs = NLP_HEALTH_CACHE_MS } = {}) {
  if (cachedHealth && Date.now() - cachedHealth.checkedAt < maxAgeMs) {
    return cachedHealth.result;
  }

  const result = await probeNlpHealth();
  cachedHealth = { checkedAt: Date.now(), result };
  return result;
}

async function probeNlpHealth() {
  const base = { url: NLP_ENGINE_URL, checkedAt: new Date().toISOString() };

  let response;
  try {
    response = await requestNlp('/health', { timeoutMs: NLP_HEALTH_TIMEOUT_MS });
  } catch (err) {
    return { ...base, reachable: false, ready: false, status: 'unreachable', error: err.message };
  }

  if (!response.ok) {
    return {
      ...base,
      reachable: true,
      ready: false,
      status: 'error',
      error: `NLP engine health check returned HTTP ${response.status}: ${await readErrorDetail(response)}`,
    };
  }

  let body;
  try {
    body = await response.json();
  } catch (err) {
    return {
      ...base,
      reachable: true,
      ready: false,
      status: 'error',
      error: `NLP engine health check returned a non-JSON body: ${err.message}`,
    };
  }

  return {
    ...base,
    reachable: true,
    // An older nlp-engine build reports only {"status":"ok"} with no `ready`
    // field. Treat that as ready rather than blocking every upload against a
    // service that is, as far as it knows how to tell us, fine.
    ready: body.ready ?? body.status === 'ok',
    status: body.status ?? 'unknown',
    checks: body.checks ?? null,
    error: null,
  };
}

/** Discard any cached health result — used after a failed analyze call. */
export function invalidateNlpHealthCache() {
  cachedHealth = null;
}

/**
 * POST a saved syllabus file to the nlp-engine's /analyze endpoint and return
 * its parsed response. Throws NlpServiceError on any failure.
 */
export async function analyzeSyllabusFile(filePath, originalName) {
  let fileBuffer;
  try {
    fileBuffer = await fs.readFile(filePath);
  } catch (err) {
    throw new NlpServiceError(`Could not read the uploaded file at ${filePath}: ${err.message}`, {
      code: 'NLP_ERROR',
      cause: err,
    });
  }

  const formData = new FormData();
  formData.append('file', new Blob([fileBuffer]), originalName);

  let response;
  try {
    response = await requestNlp('/analyze', {
      method: 'POST',
      body: formData,
      timeoutMs: NLP_ANALYZE_TIMEOUT_MS,
    });
  } catch (err) {
    // Whatever we believed about the engine's health is now stale.
    invalidateNlpHealthCache();
    throw err;
  }

  if (!response.ok) {
    invalidateNlpHealthCache();
    const detail = await readErrorDetail(response);

    // 4xx from the engine is a verdict on *this file* (wrong type, empty, no
    // extractable skills) — not a service fault, so don't report it as one.
    if (response.status >= 400 && response.status < 500) {
      throw new NlpServiceError(detail, { code: 'NLP_REJECTED_FILE' });
    }
    // 503 specifically means one of its own dependencies is missing (database
    // unreachable, job_skills unseeded) — retryable once that's fixed.
    if (response.status === 503) {
      throw new NlpServiceError(detail, { code: 'NLP_UNAVAILABLE' });
    }
    throw new NlpServiceError(`NLP engine failed with HTTP ${response.status}: ${detail}`, {
      code: 'NLP_ERROR',
    });
  }

  let data;
  try {
    data = await response.json();
  } catch (err) {
    throw new NlpServiceError(`NLP engine returned a non-JSON response: ${err.message}`, {
      code: 'NLP_BAD_RESPONSE',
      cause: err,
    });
  }

  assertAnalyzeShape(data);
  return data;
}

/**
 * Fail loudly on a response we can't trust, rather than storing nulls and
 * empty skill lists in gap_reports and calling it an analysis.
 */
function assertAnalyzeShape(data) {
  const problems = [];

  if (!data || typeof data !== 'object') {
    throw new NlpServiceError('NLP engine returned a non-object response body', {
      code: 'NLP_BAD_RESPONSE',
    });
  }
  if (typeof data.gap_score !== 'number' || Number.isNaN(data.gap_score)) {
    problems.push(`gap_score must be a number (got ${JSON.stringify(data.gap_score)})`);
  }
  for (const field of ['extracted_skills', 'matched_skills', 'unmatched_skills']) {
    if (!Array.isArray(data[field])) {
      problems.push(`${field} must be an array (got ${JSON.stringify(data[field])})`);
    }
  }
  // nep_score is legitimately null when nep_competencies isn't seeded, so
  // only a wrong *type* is a problem here.
  if (data.nep_score != null && typeof data.nep_score !== 'number') {
    problems.push(`nep_score must be a number or null (got ${JSON.stringify(data.nep_score)})`);
  }

  if (problems.length > 0) {
    throw new NlpServiceError(`Unexpected response shape from NLP engine: ${problems.join('; ')}`, {
      code: 'NLP_BAD_RESPONSE',
    });
  }
}
