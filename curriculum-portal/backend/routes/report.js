import { Router } from 'express';

import { pool } from '../db.js';
import { authenticateToken } from '../middleware/auth.js';

const router = Router();

// GET /api/report/:id
// Fetch a saved gap analysis report (gap_reports.id), including the full
// skill-match detail persisted alongside it in `reports`. Scoped to the
// logged-in user's institute — reports belonging to another institute are
// reported as not found rather than forbidden, to avoid confirming they exist.
router.get('/:id', authenticateToken, async (req, res) => {
  const { id } = req.params;
  if (!/^\d+$/.test(id)) {
    return res.status(400).json({ error: 'Report id must be a positive integer' });
  }

  try {
    const { rows: gapRows } = await pool.query(
      `SELECT gr.id, gr.syllabus_id, gr.gap_score, gr.nep_score, gr.created_at,
              s.filename, s.institute_id
       FROM gap_reports gr
       JOIN syllabi s ON s.id = gr.syllabus_id
       WHERE gr.id = $1`,
      [id]
    );

    if (gapRows.length === 0 || gapRows[0].institute_id !== req.user.instituteId) {
      return res.status(404).json({ error: `No report found with id=${id}` });
    }

    const gapReport = gapRows[0];

    const { rows: summaryRows } = await pool.query(
      'SELECT summary FROM reports WHERE syllabus_id = $1 ORDER BY generated_at DESC LIMIT 1',
      [gapReport.syllabus_id]
    );
    const summary = summaryRows[0]?.summary || {};

    res.json({
      reportId: gapReport.id,
      syllabusId: gapReport.syllabus_id,
      filename: gapReport.filename,
      gapScore: gapReport.gap_score,
      nepScore: gapReport.nep_score,
      createdAt: gapReport.created_at,
      matchedSkills: summary.matchedSkills || [],
      missingSkills: summary.missingSkills || [],
    });
  } catch (dbErr) {
    console.error('Failed to fetch report:', dbErr);
    res.status(500).json({ error: 'Failed to fetch report' });
  }
});

export default router;
