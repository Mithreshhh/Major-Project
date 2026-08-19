import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.db import fetch_job_skills, fetch_nep_competencies
from app.matching_engine import (
    DEFAULT_SIMILARITY_THRESHOLD,
    compute_gap_analysis,
    compute_nep_alignment,
)
from app.skill_extraction import extract_skills_from_file

logger = logging.getLogger("nlp-engine.analyze")

router = APIRouter()

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def _compute_nep_alignment_or_none(extracted_skills: list) -> dict:
    """
    Score the syllabus against the NEP competency set, degrading to a null
    score rather than failing the request.

    NEP alignment is a secondary signal: job-market gap analysis is what
    /analyze exists for, and an unseeded nep_competencies table or a
    transient failure scoring it shouldn't cost the caller the gap analysis
    it already paid for. A null nep_score reads as "not scored" everywhere
    downstream (the backend stores NULL, the frontend renders an empty
    gauge), which is honest; inventing a number would not be.
    """
    empty = {"covered_competencies": [], "missing_competencies": [], "nep_score": None}
    try:
        competencies = fetch_nep_competencies()
    except RuntimeError as exc:
        logger.warning("Skipping NEP alignment - could not load nep_competencies: %s", exc)
        return empty

    if not competencies:
        logger.warning(
            "Skipping NEP alignment - nep_competencies is empty. "
            "Run database/seed_nep.py to populate it."
        )
        return empty

    try:
        alignment = compute_nep_alignment(extracted_skills, competencies)
    except (ValueError, RuntimeError) as exc:
        logger.warning("Skipping NEP alignment - matching failed: %s", exc)
        return empty

    return alignment


# POST /analyze
# Ties skill_extraction.py + matching_engine.py together: given an uploaded
# syllabus file, extract its skill phrases, compare them against both the
# job-market skill list (job_skills table) and the NEP competency set
# (nep_competencies table), and return the gap analysis plus NEP alignment.
@router.post("/analyze")
async def analyze_syllabus(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix or 'unknown'}'. Expected .pdf or .docx.",
        )

    try:
        contents = await file.read()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {exc}") from exc

    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Skill extraction works off a file path, so persist the upload to a
    # temp file for the duration of extraction, then clean it up.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        extracted_skills = extract_skills_from_file(tmp_path)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        raise HTTPException(status_code=422, detail=f"Failed to extract skills: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Skill extraction failed: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if not extracted_skills:
        raise HTTPException(status_code=422, detail="No skill phrases could be extracted from this file")

    try:
        job_skills = fetch_job_skills()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Could not load job_skills from database: {exc}") from exc

    if not job_skills:
        raise HTTPException(
            status_code=503,
            detail="job_skills table is empty. Run database/import_onet.py to seed it first.",
        )

    try:
        gap_analysis = compute_gap_analysis(extracted_skills, job_skills)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=f"Matching failed: {exc}") from exc

    nep_alignment = _compute_nep_alignment_or_none(extracted_skills)

    return {
        "filename": file.filename,
        "extracted_skills": extracted_skills,
        "matched_skills": gap_analysis["matched_skills"],
        "unmatched_skills": gap_analysis["unmatched_skills"],
        "gap_score": gap_analysis["gap_score"],
        # null when nep_competencies is unseeded or scoring it failed - see
        # _compute_nep_alignment_or_none(). Higher is better, unlike gap_score.
        "nep_score": nep_alignment["nep_score"],
        "nep_covered_competencies": nep_alignment["covered_competencies"],
        "nep_missing_competencies": nep_alignment["missing_competencies"],
        "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
    }
