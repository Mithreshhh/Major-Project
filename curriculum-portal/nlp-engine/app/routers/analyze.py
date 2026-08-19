import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.db import fetch_job_skills
from app.matching_engine import DEFAULT_SIMILARITY_THRESHOLD, compute_gap_analysis
from app.skill_extraction import extract_skills_from_file

router = APIRouter()

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


# POST /analyze
# Ties skill_extraction.py + matching_engine.py together: given an uploaded
# syllabus file, extract its skill phrases, compare them against the
# job-market skill list (job_skills table), and return the gap analysis.
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

    return {
        "filename": file.filename,
        "extracted_skills": extracted_skills,
        "matched_skills": gap_analysis["matched_skills"],
        "unmatched_skills": gap_analysis["unmatched_skills"],
        "gap_score": gap_analysis["gap_score"],
        "similarity_threshold": DEFAULT_SIMILARITY_THRESHOLD,
    }
