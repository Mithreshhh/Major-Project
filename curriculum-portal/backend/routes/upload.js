import { Router } from 'express';
import multer from 'multer';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { pool } from '../db.js';
import { REQUIRE_NLP_READY } from '../config.js';
import { authenticateToken } from '../middleware/auth.js';
import { analyzeSubmission } from '../services/analyzeSubmission.js';
import { checkNlpHealth, httpStatusForNlpError } from '../services/nlpClient.js';

const router = Router();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UPLOAD_DIR = path.join(__dirname, '..', 'uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const ALLOWED_EXTENSIONS = new Set(['.pdf', '.docx']);
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB

// User-facing headline per NlpServiceError code (see services/nlpClient.js).
// The raw error text still goes out in `details` — this is just so the user
// isn't told "the service is down" when the real answer is "we couldn't read
// anything useful out of your file".
const ANALYZE_ERROR_MESSAGES = {
  NLP_REJECTED_FILE: 'This file could not be analyzed',
  NLP_TIMEOUT: 'The analysis service took too long to respond',
  NLP_UNREACHABLE: 'The analysis service is unavailable',
  NLP_UNAVAILABLE: 'The analysis service is not fully configured',
  NLP_BAD_RESPONSE: 'The analysis service returned an unusable result',
};

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, UPLOAD_DIR),
  filename: (req, file, cb) => {
    const uniqueSuffix = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
    cb(null, `${uniqueSuffix}${path.extname(file.originalname)}`);
  },
});

const upload = multer({
  storage,
  limits: { fileSize: MAX_FILE_SIZE_BYTES },
  fileFilter: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase();
    if (!ALLOWED_EXTENSIONS.has(ext)) {
      cb(new Error(`Unsupported file type '${ext}'. Only .pdf and .docx are allowed.`));
      return;
    }
    cb(null, true);
  },
});

// POST /api/upload
// Saves the uploaded syllabus, sends it to the nlp-engine for real skill
// extraction and gap analysis (see services/analyzeSubmission.js), and
// persists the result to gap_reports (scores) and reports (full detail).
router.post('/', authenticateToken, async (req, res) => {
  // Pre-flight the NLP engine *before* multer reads the request body, so a
  // down or still-warming service costs the user a fast 503 instead of a full
  // file upload followed by a failure. The health result is cached for a few
  // seconds (see NLP_HEALTH_CACHE_MS), so this doesn't add a round trip to
  // every upload in a burst.
  if (REQUIRE_NLP_READY) {
    // checkNlpHealth() is written not to throw, but this handler is async and
    // Express 4 wouldn't catch a rejection here — it would take the process
    // down. Treat any surprise as "not ready" rather than risking that.
    let health;
    try {
      health = await checkNlpHealth();
    } catch (healthErr) {
      console.error('NLP health check threw unexpectedly:', healthErr);
      health = { ready: false, status: 'error', error: healthErr.message };
    }

    if (!health.ready) {
      return res.status(503).json({
        error: 'The analysis service is not available right now, so uploads are paused.',
        details: health.error || `NLP engine reported status='${health.status}'`,
        hint: 'Check GET /api/health/nlp for which dependency is not ready.',
        nlp: health,
      });
    }
  }

  upload.single('syllabus')(req, res, async (multerErr) => {
    if (multerErr) {
      return res.status(400).json({ error: multerErr.message });
    }
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded. Expected a "syllabus" file field.' });
    }

    let syllabusId;
    try {
      const { rows } = await pool.query(
        'INSERT INTO syllabi (institute_id, filename, file_path) VALUES ($1, $2, $3) RETURNING id',
        [req.user.instituteId, req.file.originalname, req.file.path]
      );
      syllabusId = rows[0].id;
    } catch (dbErr) {
      console.error('Failed to save syllabus record:', dbErr);
      return res.status(500).json({ error: 'Failed to save syllabus record' });
    }

    let analysis;
    try {
      analysis = await analyzeSubmission(req.file.path, req.file.originalname);
    } catch (analyzeErr) {
      console.error('analyzeSubmission() failed:', analyzeErr);
      // The syllabus row is deliberately left in place: the file was stored
      // successfully, and keeping the record makes a retry (or a look at what
      // was uploaded) possible. It just has no gap_report attached yet.
      return res.status(httpStatusForNlpError(analyzeErr)).json({
        error: ANALYZE_ERROR_MESSAGES[analyzeErr.code] || 'Failed to analyze syllabus',
        details: analyzeErr.message,
        code: analyzeErr.code || 'NLP_ERROR',
        syllabusId,
      });
    }

    let gapReportId;
    try {
      const { rows } = await pool.query(
        `INSERT INTO gap_reports (syllabus_id, gap_score, nep_score)
         VALUES ($1, $2, $3)
         RETURNING id, created_at`,
        [syllabusId, analysis.gapScore, analysis.nepScore]
      );
      gapReportId = rows[0].id;

      await pool.query('INSERT INTO reports (syllabus_id, summary) VALUES ($1, $2)', [
        syllabusId,
        JSON.stringify(analysis),
      ]);
    } catch (dbErr) {
      console.error('Failed to save gap report:', dbErr);
      return res.status(500).json({ error: 'Failed to save gap analysis report' });
    }

    res.status(201).json({
      reportId: gapReportId,
      syllabusId,
      gapScore: analysis.gapScore,
      nepScore: analysis.nepScore,
      extractedSkills: analysis.extractedSkills,
      matchedSkills: analysis.matchedSkills,
      missingSkills: analysis.missingSkills,
      // Surfaced so a null NEP score reads as "not scored" rather than "0".
      ...(analysis.nepScore === null && {
        nepScoreUnavailable:
          'NEP competencies are not seeded — run database/seed_nep.py to enable NEP scoring.',
      }),
    });
  });
});

export default router;
