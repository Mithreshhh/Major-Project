import fs from 'node:fs';

import { NLP_ENGINE_URL, USE_MOCK_ANALYSIS } from '../config.js';

const MOCK_ANALYSIS_RESULT = {
  gapScore: 72,
  matchedSkills: ['Data Structures', 'OOP'],
  missingSkills: ['Cloud Computing', 'DevOps'],
  nepScore: 65,
};

/**
 * Analyze a saved syllabus file and return its gap-analysis result.
 *
 * Currently returns fixed mock data (USE_MOCK_ANALYSIS=true by default, see
 * config.js) so /upload can be built and tested without the Python NLP
 * service running.
 *
 * TODO: real NLP service integration point. Set USE_MOCK_ANALYSIS=false and
 * this will call callRealAnalysisService() below, which POSTs the file to
 * nlp-engine's /analyze endpoint and adapts its response into this same
 * { gapScore, matchedSkills, missingSkills, nepScore } shape.
 */
export async function analyzeSubmission(filePath, originalName) {
  if (USE_MOCK_ANALYSIS) {
    return { ...MOCK_ANALYSIS_RESULT };
  }

  return callRealAnalysisService(filePath, originalName);
}

/**
 * Real implementation: sends the syllabus file to the nlp-engine FastAPI
 * service and adapts its response. Not used while USE_MOCK_ANALYSIS=true.
 */
async function callRealAnalysisService(filePath, originalName) {
  const fileBuffer = fs.readFileSync(filePath);
  const formData = new FormData();
  formData.append('file', new Blob([fileBuffer]), originalName);

  let response;
  try {
    response = await fetch(`${NLP_ENGINE_URL}/analyze`, {
      method: 'POST',
      body: formData,
    });
  } catch (networkErr) {
    throw new Error(`Could not reach nlp-engine at ${NLP_ENGINE_URL}: ${networkErr.message}`);
  }

  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(`nlp-engine returned ${response.status}: ${detail}`);
  }

  const data = await response.json();
  return {
    gapScore: data.gap_score,
    matchedSkills: data.matched_skills,
    missingSkills: data.unmatched_skills,
    // TODO: nep_score once NEP competency matching is implemented in nlp-engine
    nepScore: null,
  };
}
