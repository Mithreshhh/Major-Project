"""
db.py

Minimal PostgreSQL access helper for the nlp-engine service. Only used to
pull the job-market skill list (job_skills table, populated by
database/import_onet.py) for the /analyze endpoint's gap analysis.
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


def fetch_job_skills() -> list:
    """Return the deduplicated list of distinct skill_name values from job_skills."""
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT skill_name FROM job_skills ORDER BY skill_name;")
            rows = cur.fetchall()
        return [row[0] for row in rows if row[0]]
    except psycopg2.Error as exc:
        raise RuntimeError(f"Failed to query job_skills: {exc}") from exc
    finally:
        if conn:
            conn.close()
