import { Router } from 'express';

import { pool } from '../db.js';
import { authenticateToken } from '../middleware/auth.js';

const router = Router();

const DEFAULT_LIMIT = 50;

// GET /api/reports
// List all gap analysis reports for the logged-in user's institute, most
// recent first.
router.get('/', authenticateToken, async (req, res) => {
  try {
    const { rows } = await pool.query(
      `SELECT gr.id, gr.syllabus_id, gr.gap_score, gr.nep_score, gr.created_at,
              s.filename
       FROM gap_reports gr
       JOIN syllabi s ON s.id = gr.syllabus_id
       WHERE s.institute_id = $1
       ORDER BY gr.created_at DESC
       LIMIT $2`,
      [req.user.instituteId, DEFAULT_LIMIT]
    );

    res.json({
      reports: rows.map((row) => ({
        reportId: row.id,
        syllabusId: row.syllabus_id,
        filename: row.filename,
        gapScore: row.gap_score,
        nepScore: row.nep_score,
        createdAt: row.created_at,
      })),
    });
  } catch (dbErr) {
    console.error('Failed to list reports:', dbErr);
    res.status(500).json({ error: 'Failed to list reports' });
  }
});

export default router;
