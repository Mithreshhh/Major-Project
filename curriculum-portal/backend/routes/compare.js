import { Router } from 'express';

import { authenticateToken } from '../middleware/auth.js';
import { getInstituteComparison } from '../services/compareInstitutes.js';

const router = Router();

const SORTABLE_FIELDS = new Set(['name', 'gapScore', 'nepScore', 'reportCount', 'lastAnalyzedAt']);
const DEFAULT_SORT = 'gapScore';
const DEFAULT_ORDER = 'asc';

/**
 * Sort institutes by one field.
 *
 * Nulls always sink to the bottom regardless of direction: an unscored
 * institute isn't "the best" when sorting ascending, and treating null as 0
 * would rank it as a perfect gap score.
 */
function sortInstitutes(institutes, sortBy, order) {
  const direction = order === 'desc' ? -1 : 1;

  return [...institutes].sort((a, b) => {
    const left = a[sortBy];
    const right = b[sortBy];

    if (left === null || left === undefined) return 1;
    if (right === null || right === undefined) return -1;

    if (typeof left === 'string' && typeof right === 'string') {
      return left.localeCompare(right) * direction;
    }
    return (left - right) * direction;
  });
}

// GET /api/compare
// Every institute's most recent gap analysis, side by side.
//
// Query params:
//   sortBy  name | gapScore | nepScore | reportCount | lastAnalyzedAt  (default gapScore)
//   order   asc | desc                                                 (default asc)
//
// Sorting is applied server-side so the contract is stable for any client,
// but the dataset is small and the frontend also sorts locally on header
// click rather than re-fetching for every toggle.
//
// NOTE: unlike GET /report/:id, this endpoint deliberately shows data across
// institute boundaries — that is the feature. It exposes only aggregate
// scores and never another institute's syllabi, filenames, or skill detail.
// It still requires a login; whether every logged-in user should see the
// cross-institute leaderboard is a product decision worth revisiting before
// this ships to real tenants.
router.get('/', authenticateToken, async (req, res) => {
  const sortBy = SORTABLE_FIELDS.has(req.query.sortBy) ? req.query.sortBy : DEFAULT_SORT;
  const order = req.query.order === 'desc' ? 'desc' : DEFAULT_ORDER;

  if (req.query.sortBy && !SORTABLE_FIELDS.has(req.query.sortBy)) {
    return res.status(400).json({
      error: `Unknown sortBy '${req.query.sortBy}'.`,
      allowed: [...SORTABLE_FIELDS],
    });
  }

  try {
    const comparison = await getInstituteComparison();

    res.json({
      ...comparison,
      sortBy,
      order,
      count: comparison.institutes.length,
      institutes: sortInstitutes(comparison.institutes, sortBy, order),
    });
  } catch (err) {
    console.error('Failed to build institute comparison:', err);
    res.status(500).json({ error: 'Failed to load institute comparison' });
  }
});

export default router;
