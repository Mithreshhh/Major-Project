import { analyzeSyllabusFile } from './nlpClient.js';

/**
 * Analyze a saved syllabus file and return its gap-analysis result.
 *
 * Sends the file to the nlp-engine's /analyze endpoint and adapts the
 * response to this app's camelCase shape. Throws NlpServiceError if the
 * analysis can't be completed — see nlpClient.js for the failure codes and
 * httpStatusForNlpError() for how routes turn them into status codes.
 *
 * @returns {Promise<{
 *   extractedSkills: string[],   // skill phrases found in the syllabus
 *   matchedSkills: string[],     // job-market skills the syllabus covers
 *   missingSkills: string[],     // job-market skills it doesn't
 *   gapScore: number,            // 0-100, % of job-market skills missing (lower is better)
 *   nepScore: number | null,     // 0-100, % of NEP competencies covered (higher is better);
 *                                //   null when nep_competencies isn't seeded
 *   nepCoveredCompetencies: string[],
 *   nepMissingCompetencies: string[],
 *   similarityThreshold: number | null,
 * }>}
 */
export async function analyzeSubmission(filePath, originalName) {
  const data = await analyzeSyllabusFile(filePath, originalName);

  return {
    extractedSkills: data.extracted_skills,
    matchedSkills: data.matched_skills,
    missingSkills: data.unmatched_skills,
    gapScore: data.gap_score,
    // `?? null` keeps an nlp-engine that predates NEP scoring from writing
    // `undefined` into gap_reports.nep_score.
    nepScore: data.nep_score ?? null,
    nepCoveredCompetencies: data.nep_covered_competencies ?? [],
    nepMissingCompetencies: data.nep_missing_competencies ?? [],
    similarityThreshold: data.similarity_threshold ?? null,
  };
}
