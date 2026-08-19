"""
import_onet.py

Reads O*NET's "Technology Skills.txt" export, filters it down to CS-relevant
occupations, cleans the rows, and loads them into the `job_skills` table
(see schema.sql).

Expected input format (tab-delimited, as distributed by O*NET):
    O*NET-SOC Code | Title | Example | Commodity Code | Commodity Title | Hot Technology | In Demand

We map:
    Title           -> occupation_title
    Example         -> skill_name
    Commodity Title -> skill_category

Usage:
    python import_onet.py --file "Technology Skills.txt"
    python import_onet.py --file "Technology Skills.txt" --truncate

Requires: psycopg2-binary, python-dotenv (see database/requirements.txt)
Reads DB connection settings from database/.env (see .env.example).
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# Only these occupations are relevant to the CS/software curriculum use case.
# O*NET occupation titles change slightly between taxonomy versions (e.g.
# "Database Administrators" vs "Database Administrators and Architects"), so
# we match by substring rather than exact equality.
TARGET_OCCUPATIONS = [
    "Software Developers",
    "Data Scientists",
    "Computer Systems Analysts",
    "Web Developers",
    "Database Administrators",
]

EXPECTED_COLUMNS = {"Title", "Example", "Commodity Title"}


def load_db_config():
    """Load PostgreSQL connection settings from a .env file next to this script."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)

    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": os.getenv("POSTGRES_PORT", "5432"),
        "dbname": os.getenv("POSTGRES_DB", "curriculum_portal"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
    }


def is_target_occupation(title: str) -> bool:
    """True if `title` matches (as a substring, case-insensitive) one of the
    CS-relevant occupations we care about."""
    title_lower = title.lower()
    return any(target.lower() in title_lower for target in TARGET_OCCUPATIONS)


def read_and_filter_rows(file_path: Path):
    """
    Read the O*NET Technology Skills TSV file and yield cleaned
    (occupation_title, skill_name, skill_category) tuples for CS-relevant
    occupations only.

    Malformed or incomplete rows are skipped with a warning rather than
    aborting the whole import.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"O*NET file not found: {file_path}")

    seen = set()  # dedupe (occupation_title, skill_name) pairs within this file
    row_count = 0
    skipped_count = 0

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")

        missing_columns = EXPECTED_COLUMNS - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"Input file is missing expected column(s): {sorted(missing_columns)}. "
                f"Found columns: {reader.fieldnames}"
            )

        for line_num, row in enumerate(reader, start=2):  # header is line 1
            row_count += 1
            try:
                occupation_title = (row.get("Title") or "").strip()
                skill_name = (row.get("Example") or "").strip()
                skill_category = (row.get("Commodity Title") or "").strip() or None

                if not occupation_title or not skill_name:
                    skipped_count += 1
                    continue

                if not is_target_occupation(occupation_title):
                    continue

                dedupe_key = (occupation_title.lower(), skill_name.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                yield (occupation_title, skill_name, skill_category)

            except Exception as exc:  # noqa: BLE001 - log and continue, don't abort the import
                skipped_count += 1
                print(f"  [warn] skipping malformed row at line {line_num}: {exc}", file=sys.stderr)

    print(f"Read {row_count} rows, skipped {skipped_count} malformed/empty rows.")


def load_rows_into_db(rows, db_config: dict, truncate: bool = False):
    """
    Bulk-insert cleaned rows into job_skills.
    Uses ON CONFLICT DO NOTHING against the (occupation_title, skill_name)
    unique constraint so re-running the import is idempotent.
    """
    rows = list(rows)
    if not rows:
        print("No matching rows to import. Nothing to do.")
        return

    conn = None
    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = False
        with conn.cursor() as cur:
            if truncate:
                print("Truncating job_skills before import (--truncate was passed)...")
                cur.execute("TRUNCATE TABLE job_skills RESTART IDENTITY;")

            inserted = execute_values(
                cur,
                """
                INSERT INTO job_skills (occupation_title, skill_name, skill_category)
                VALUES %s
                ON CONFLICT (occupation_title, skill_name) DO NOTHING
                """,
                rows,
                fetch=False,
            )
        conn.commit()
        print(f"Loaded {len(rows)} candidate rows into job_skills (duplicates skipped via ON CONFLICT).")

    except psycopg2.OperationalError as exc:
        print(f"[error] could not connect to the database: {exc}", file=sys.stderr)
        raise
    except psycopg2.Error as exc:
        if conn:
            conn.rollback()
        print(f"[error] database error during import, rolled back: {exc}", file=sys.stderr)
        raise
    finally:
        if conn:
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Import O*NET Technology Skills into job_skills.")
    parser.add_argument(
        "--file",
        default="Technology Skills.txt",
        help='Path to the O*NET "Technology Skills.txt" export (default: %(default)s)',
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate job_skills before importing (default: append/upsert).",
    )
    args = parser.parse_args()

    file_path = Path(args.file)

    try:
        rows = read_and_filter_rows(file_path)
        db_config = load_db_config()
        load_rows_into_db(rows, db_config, truncate=args.truncate)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except psycopg2.Error:
        # Already logged with details in load_rows_into_db
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        print(f"[error] unexpected failure during import: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
