import 'dotenv/config';

if (!process.env.JWT_SECRET) {
  console.warn(
    'WARNING: JWT_SECRET is not set. Using an insecure default — do not use this outside local dev.'
  );
}

export const JWT_SECRET = process.env.JWT_SECRET || 'insecure-dev-secret-change-me';
export const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || '7d';

export const NLP_ENGINE_URL = process.env.NLP_ENGINE_URL || 'http://localhost:8000';

// Controls whether POST /upload uses mock analysis data or calls the real
// nlp-engine service. See services/analyzeSubmission.js.
export const USE_MOCK_ANALYSIS = (process.env.USE_MOCK_ANALYSIS ?? 'true').toLowerCase() !== 'false';
