import { Router } from 'express';
import multer from 'multer';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { pool } from '../db.js';
import { authenticateToken } from '../middleware/auth.js';
import { analyzeSubmission } from '../services/analyzeSubmission.js';

const router = Router();

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const UPLOAD_DIR = path.join(__dirname, '..', 'uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const ALLOWED_EXTENSIONS = new Set(['.pdf', '.docx']);
const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024; // 10MB

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
// Saves the uploaded syllabus, runs analyzeSubmission() (mock data by
// default — see services/analyzeSubmission.js), and persists the result to
// gap_reports (scores) and reports (full skill-match detail).
router.post('/', authenticateToken, (req, res) => {
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
      return res.status(502).json({
        error: 'Failed to analyze syllabus',
        details: analyzeErr.message,
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
      matchedSkills: analysis.matchedSkills,
      missingSkills: analysis.missingSkills,
    });
  });
});

export default router;
