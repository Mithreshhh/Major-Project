/**
 * compareInstitutes.js
 *
 * Data source for GET /api/compare — each institute's most recent gap
 * analysis, side by side.
 *
 * Mock and real implementations both live here and return the identical
 * shape, selected by COMPARE_USE_MOCK (see config.js). Switching to live
 * data is that one env var: the SQL below is already written and is what
 * runs the moment the flag is false, so nothing gets rewritten later.
 *
 * Every response carries `source: "mock" | "database"`. A comparison table
 * of institutions is exactly the kind of screen someone screenshots into a
 * report, so the payload has to say out loud when the numbers are invented —
 * the UI renders a banner off this field.
 */
import { pool } from '../db.js';
import { COMPARE_USE_MOCK } from '../config.js';

/**
 * Sample institutes for UI work while the database is down. Scores are
 * spread deliberately: a strong performer, two mid-range, and one weak, so
 * sorting, colour banding, and the bar chart all have something to show.
 */
const MOCK_INSTITUTES = [
  {
    instituteId: 1,
    name: 'Ivy Tech Institute',
    code: 'IVY-001',
    location: 'Bengaluru, KA',
    gapScore: 28.4,
    nepScore: 71.2,
    reportCount: 14,
    latestReportId: 101,
    lastAnalyzedAt: '2026-08-28T10:15:00.000Z',
  },
  {
    instituteId: 2,
    name: 'Metro State College',
    code: 'MSC-114',
    location: 'Pune, MH',
    gapScore: 44.1,
    nepScore: 52.8,
    reportCount: 9,
    latestReportId: 102,
    lastAnalyzedAt: '2026-08-30T14:02:00.000Z',
  },
  {
    instituteId: 3,
    name: 'Northfield University',
    code: 'NFU-207',
    location: 'Hyderabad, TG',
    gapScore: 51.7,
    nepScore: 46.5,
    reportCount: 21,
    latestReportId: 103,
    lastAnalyzedAt: '2026-09-01T08:40:00.000Z',
  },
  {
    instituteId: 4,
    name: 'Riverside Polytechnic',
    code: 'RVP-052',
    location: 'Kochi, KL',
    gapScore: 72.9,
    nepScore: 23.6,
    reportCount: 5,
    latestReportId: 104,
    lastAnalyzedAt: '2026-08-19T16:55:00.000Z',
  },
];

/**
 * One row per institute that has at least one gap report, carrying its most
 * recent scores.
 *
 * DISTINCT ON is Postgres-specific but is the direct way to express "the
 * latest row per group" — the portable alternative is a window function plus
 * an outer filter, which is more code for the same plan. The ORDER BY inside
 * the CTE is what selects which row survives per institute, so it isn't
 * cosmetic and must stay.
 *
 * Institutes with no reports are absent rather than shown with null scores:
 * a comparison table is for comparing, and a row of dashes invites the reader
 * to infer a zero.
 */
const COMPARISON_QUERY = `
  WITH latest_report AS (
    SELECT DISTINCT ON (s.institute_id)
           s.institute_id,
           gr.id            AS report_id,
           gr.gap_score,
           gr.nep_score,
           gr.created_at
    FROM gap_reports gr
    JOIN syllabi s ON s.id = gr.syllabus_id
    WHERE s.institute_id IS NOT NULL
    ORDER BY s.institute_id, gr.created_at DESC, gr.id DESC
  ),
  report_counts AS (
    SELECT s.institute_id, COUNT(*) AS report_count
    FROM gap_reports gr
    JOIN syllabi s ON s.id = gr.syllabus_id
    WHERE s.institute_id IS NOT NULL
    GROUP BY s.institute_id
  )
  SELECT i.id           AS institute_id,
         i.name,
         i.code,
         i.location,
         lr.gap_score,
         lr.nep_score,
         lr.report_id   AS latest_report_id,
         lr.created_at  AS last_analyzed_at,
         COALESCE(rc.report_count, 0) AS report_count
  FROM institutes i
  JOIN latest_report lr ON lr.institute_id = i.id
  LEFT JOIN report_counts rc ON rc.institute_id = i.id
  ORDER BY i.name ASC
`;

/**
 * Coerce one database row into the API shape.
 *
 * NUMERIC columns arrive from pg as strings to avoid float precision loss,
 * and gap_reports.nep_score is nullable, so `Number(null)` would quietly
 * become 0 — a real "not scored" turning into a real-looking zero. Null is
 * preserved instead and the frontend renders it as "not scored".
 */
function toInstituteRow(row) {
  return {
    instituteId: row.institute_id,
    name: row.name,
    code: row.code ?? null,
    location: row.location ?? null,
    gapScore: row.gap_score === null ? null : Number(row.gap_score),
    nepScore: row.nep_score === null ? null : Number(row.nep_score),
    reportCount: Number(row.report_count),
    latestReportId: row.latest_report_id,
    lastAnalyzedAt: row.last_analyzed_at,
  };
}

async function fetchFromDatabase() {
  const { rows } = await pool.query(COMPARISON_QUERY);
  return rows.map(toInstituteRow);
}

function fetchMock() {
  // Copied, not returned by reference — a caller sorting the array in place
  // would otherwise mutate the module-level constant for every later request.
  return MOCK_INSTITUTES.map((institute) => ({ ...institute }));
}

/**
 * Institute comparison data.
 *
 * @returns {Promise<{source: 'mock'|'database', generatedAt: string, institutes: object[]}>}
 */
export async function getInstituteComparison() {
  const useMock = COMPARE_USE_MOCK;
  const institutes = useMock ? fetchMock() : await fetchFromDatabase();

  return {
    source: useMock ? 'mock' : 'database',
    generatedAt: new Date().toISOString(),
    institutes,
  };
}
