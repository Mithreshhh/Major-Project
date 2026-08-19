"""
db.py

Minimal PostgreSQL access helper for the nlp-engine service. Used to pull
the two reference sets the /analyze endpoint scores a syllabus against:

    job_skills       - job-market demand (populated by database/import_onet.py)
    nep_competencies - NEP competency set (populated by database/seed_nep.py)

and to report on their state for the /health readiness check.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/curriculum_portal"
)


def get_connection():
    """Open a new PostgreSQL connection, raising a clear error on failure."""
    try:
        return psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as exc:
        raise RuntimeError(f"Could not connect to database at {DATABASE_URL}: {exc}") from exc


def _fetch_distinct(table: str, column: str) -> list:
    """Return the sorted distinct non-empty values of one reference column."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            # Table/column names are module-level literals, never request input.
            cur.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY {column};")
            rows = cur.fetchall()
        return [row[0] for row in rows if row[0]]
    except psycopg2.Error as exc:
        raise RuntimeError(f"Failed to query {table}: {exc}") from exc
    finally:
        if conn:
            conn.close()


def fetch_job_skills() -> list:
    """Return the deduplicated list of distinct skill_name values from job_skills."""
    return _fetch_distinct("job_skills", "skill_name")


def fetch_nep_competencies() -> list:
    """Return the deduplicated list of distinct competency_name values from nep_competencies."""
    return _fetch_distinct("nep_competencies", "competency_name")


def fetch_reference_counts() -> dict:
    """
    Return {"job_skills": int, "nep_competencies": int} — distinct row counts
    for the two reference tables, in a single connection.

    Used by /health to distinguish "the database is reachable" from "the
    database is reachable but nothing has been seeded into it yet", which are
    very different answers to "can this service analyze a syllabus?".
    """
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT (SELECT COUNT(DISTINCT skill_name) FROM job_skills),
                       (SELECT COUNT(DISTINCT competency_name) FROM nep_competencies);
                """
            )
            job_skills, nep_competencies = cur.fetchone()
        return {"job_skills": int(job_skills), "nep_competencies": int(nep_competencies)}
    except psycopg2.Error as exc:
        raise RuntimeError(f"Failed to count reference tables: {exc}") from exc
    finally:
        if conn:
            conn.close()
