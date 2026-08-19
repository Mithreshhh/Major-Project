"""
matching_engine.py

Semantic matching between a syllabus's extracted skill phrases and a
job-market skill list (from the job_skills table), using Sentence-BERT
embeddings (sentence-transformers, "all-MiniLM-L6-v2").

For each job-market skill, we find its best-matching syllabus phrase by
cosine similarity. A job skill counts as "covered" if that best match is
>= SIMILARITY_THRESHOLD. The gap score is the percentage of job-market
skills with no strong match in the curriculum.

Run this file directly to execute a self-test against sample skill lists:
    python -m app.matching_engine
"""

from sentence_transformers import SentenceTransformer, util

MODEL_NAME = "all-MiniLM-L6-v2"

# A job skill is only considered "matched" by a syllabus phrase if their
# cosine similarity meets this bar. 0.6 is a reasonably strict threshold for
# MiniLM embeddings: near-paraphrases score well above it, loosely related
# terms usually fall short.
DEFAULT_SIMILARITY_THRESHOLD = 0.6

_MODEL = None


def get_model() -> SentenceTransformer:
    """Load and cache the Sentence-BERT model (loading it is relatively slow)."""
    global _MODEL
    if _MODEL is None:
        try:
            _MODEL = SentenceTransformer(MODEL_NAME)
        except Exception as exc:  # noqa: BLE001 - surface as one clear error type
            raise RuntimeError(
                f"Failed to load sentence-transformers model '{MODEL_NAME}': {exc}"
            ) from exc
    return _MODEL


def _dedupe_clean(phrases) -> list:
    """Strip whitespace, drop empties, and dedupe case-insensitively while
    preserving first-seen order and original casing."""
    cleaned = []
    seen = set()
    for phrase in phrases or []:
        text = (phrase or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def compute_similarity_matrix(syllabus_skills: list, job_skills: list):
    """
    Embed both skill lists and return their cosine similarity matrix, shaped
    (len(job_skills), len(syllabus_skills)) — row i, column j is the
    similarity between job_skills[i] and syllabus_skills[j].
    """
    if not syllabus_skills:
        raise ValueError("syllabus_skills must be a non-empty list")
    if not job_skills:
        raise ValueError("job_skills must be a non-empty list")

    model = get_model()
    try:
        syllabus_embeddings = model.encode(syllabus_skills, convert_to_tensor=True, normalize_embeddings=True)
        job_embeddings = model.encode(job_skills, convert_to_tensor=True, normalize_embeddings=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to generate embeddings: {exc}") from exc

    return util.cos_sim(job_embeddings, syllabus_embeddings)


def match_job_skills_to_curriculum(
    syllabus_skills: list, job_skills: list, threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> list:
    """
    For each job skill, find its best-matching syllabus phrase.

    Returns a list of dicts, one per job skill:
        {"job_skill": str, "best_match": str, "similarity": float, "is_matched": bool}
    """
    similarity_matrix = compute_similarity_matrix(syllabus_skills, job_skills)
    sim = similarity_matrix.cpu().numpy()

    results = []
    for i, job_skill in enumerate(job_skills):
        row = sim[i]
        best_idx = int(row.argmax())
        best_score = float(row[best_idx])
        results.append(
            {
                "job_skill": job_skill,
                "best_match": syllabus_skills[best_idx],
                "similarity": round(best_score, 4),
                "is_matched": best_score >= threshold,
            }
        )
    return results


def compute_gap_analysis(
    syllabus_skills: list, job_skills: list, threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> dict:
    """
    Compare a syllabus's skill phrases against job-market skills and compute
    a gap score: the percentage of job-market skills with no strong match
    (similarity < threshold) in the curriculum.

    Returns:
        {
            "matched_skills": [job skills covered by the syllabus],
            "unmatched_skills": [job skills missing from the syllabus],
            "gap_score": float,  # 0-100, higher = bigger gap
            "details": [per-job-skill match info, see match_job_skills_to_curriculum],
        }
    """
    syllabus_skills = _dedupe_clean(syllabus_skills)
    job_skills = _dedupe_clean(job_skills)

    if not job_skills:
        # Nothing to compare against - no gap to measure.
        return {"matched_skills": [], "unmatched_skills": [], "gap_score": 0.0, "details": []}

    if not syllabus_skills:
        # No curriculum content at all - every job skill is a gap.
        details = [
            {"job_skill": skill, "best_match": None, "similarity": 0.0, "is_matched": False}
            for skill in job_skills
        ]
        return {
            "matched_skills": [],
            "unmatched_skills": job_skills,
            "gap_score": 100.0,
            "details": details,
        }

    details = match_job_skills_to_curriculum(syllabus_skills, job_skills, threshold)
    matched = [d["job_skill"] for d in details if d["is_matched"]]
    unmatched = [d["job_skill"] for d in details if not d["is_matched"]]
    gap_score = round((len(unmatched) / len(job_skills)) * 100, 2)

    return {
        "matched_skills": matched,
        "unmatched_skills": unmatched,
        "gap_score": gap_score,
        "details": details,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

SAMPLE_SYLLABUS_SKILLS = [
    "Python programming",
    "object-oriented programming",
    "relational database design",
    "machine learning",
    "web development",
    "version control with Git",
]

SAMPLE_JOB_SKILLS = [
    "Python",
    "Java",
    "SQL",
    "Docker",
    "Machine learning",
    "React",
    "Kubernetes",
]


def test_cosine_similarity_sanity():
    """Near-identical/related phrases should score high; unrelated phrases should score low."""
    similarity_matrix = compute_similarity_matrix(SAMPLE_SYLLABUS_SKILLS, SAMPLE_JOB_SKILLS)
    sim = similarity_matrix.cpu().numpy()

    print("Cosine similarity matrix (rows = job_skills, cols = syllabus_skills):")
    print(f"{'':22}" + "".join(f"{s:>16.16}" for s in SAMPLE_SYLLABUS_SKILLS))
    for i, job_skill in enumerate(SAMPLE_JOB_SKILLS):
        row = "".join(f"{sim[i][j]:16.3f}" for j in range(len(SAMPLE_SYLLABUS_SKILLS)))
        print(f"{job_skill:22}{row}")

    python_score = sim[SAMPLE_JOB_SKILLS.index("Python")][SAMPLE_SYLLABUS_SKILLS.index("Python programming")]
    ml_score = sim[SAMPLE_JOB_SKILLS.index("Machine learning")][SAMPLE_SYLLABUS_SKILLS.index("machine learning")]
    kubernetes_best = sim[SAMPLE_JOB_SKILLS.index("Kubernetes")].max()

    print(f"\n'Python' vs 'Python programming'       -> {python_score:.3f} (expect high: closely related)")
    print(f"'Machine learning' vs 'machine learning' -> {ml_score:.3f} (expect very high: near-identical)")
    print(f"'Kubernetes' best match in syllabus      -> {kubernetes_best:.3f} (expect lower: no real match)")

    assert python_score > 0.5, "Expected 'Python' to closely match 'Python programming'"
    assert ml_score > 0.9, "Expected near-identical phrases to score very high"
    assert kubernetes_best < python_score, "Expected an unrelated skill to score lower than a real match"

    print("\nSelf-test passed: cosine similarity scores behave as expected.")


def test_gap_analysis_sanity():
    """Gap analysis on the same sample data should produce a sane matched/unmatched split."""
    result = compute_gap_analysis(SAMPLE_SYLLABUS_SKILLS, SAMPLE_JOB_SKILLS)

    print("\nGap analysis result:")
    print(f"  Matched:    {result['matched_skills']}")
    print(f"  Unmatched:  {result['unmatched_skills']}")
    print(f"  Gap score:  {result['gap_score']}%")

    assert 0 <= result["gap_score"] <= 100
    assert "Python" in result["matched_skills"], "Expected 'Python' to be matched"
    assert "Kubernetes" in result["unmatched_skills"], "Expected 'Kubernetes' to be unmatched"

    print("Self-test passed: gap analysis returns a sane result.")


if __name__ == "__main__":
    test_cosine_similarity_sanity()
    test_gap_analysis_sanity()
