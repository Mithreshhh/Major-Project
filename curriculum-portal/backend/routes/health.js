import { Router } from 'express';

import { pool } from '../db.js';
import { checkNlpHealth } from '../services/nlpClient.js';

const router = Router();

// GET /api/health
// Liveness for this service only — no dependencies touched, so it stays fast
// and can't be turned red by a downstream outage.
router.get('/', (req, res) => {
  res.json({ status: 'ok' });
});

// GET /api/health/nlp
// Is the nlp-engine up and able to analyze a syllabus right now? Uploads are
// gated on this (see routes/upload.js), so this endpoint answers "will an
// upload work?" before anyone spends time uploading a file.
//
// Returns 200 when ready, 503 when not — so `curl -f` and container probes
// can act on the status code alone, while the body explains which specific
// dependency (models, database, seed data) isn't ready.
router.get('/nlp', async (req, res) => {
  // maxAgeMs: 0 — an operator asking directly wants the current answer, not
  // a few-seconds-old cached one.
  const health = await probeNlp();
  res.status(health.ready ? 200 : 503).json(health);
});

// GET /api/health/full
// Every dependency at once: this service, Postgres, and the nlp-engine.
// Handy as the single call a startup script waits on.
router.get('/full', async (req, res) => {
  const [database, nlp] = await Promise.all([checkDatabase(), probeNlp()]);

  const ready = database.ok && nlp.ready;
  res.status(ready ? 200 : 503).json({
    status: ready ? 'ok' : 'degraded',
    ready,
    checks: { backend: { ok: true }, database, nlp },
  });
});

// A health endpoint that 500s because a health check threw is the one failure
// mode it can't afford, so an unexpected error is reported as "not ready".
async function probeNlp() {
  try {
    return await checkNlpHealth({ maxAgeMs: 0 });
  } catch (err) {
    return { ready: false, status: 'error', error: err.message };
  }
}

async function checkDatabase() {
  try {
    await pool.query('SELECT 1');
    return { ok: true, error: null };
  } catch (dbErr) {
    return { ok: false, error: dbErr.message };
  }
}

export default router;
