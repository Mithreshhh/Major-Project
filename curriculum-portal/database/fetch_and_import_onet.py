"""
fetch_and_import_onet.py

Loads the `job_skills` table from a local O*NET database export, combining
two files that describe job requirements in different ways:

    onet_raw/Technology Skills.txt
        Concrete tools and technologies an occupation uses - "Python",
        "Git", "Amazon Web Services". These match syllabus topics directly.

    onet_raw/Skills.txt
        O*NET's worker-requirement skills - "Programming", "Critical
        Thinking", "Systems Analysis" - rated per occupation for importance
        and level. Broader and more transferable than the tool list.

Both are filtered to the CS-relevant occupations in TARGET_OCCUPATIONS and
written to `job_skills` (occupation_title, skill_name, skill_category).

THE TWO FILES HAVE DIFFERENT SCHEMAS
------------------------------------
Technology Skills.txt carries both the SOC code and the occupation Title, so
it can be filtered on title directly. Skills.txt carries only the SOC code -
there is no Title column - so occupation names have to be resolved first.
This script builds that code -> title map from Occupation Data.txt when it is
present (the canonical source), and otherwise falls back to the map implied
by Technology Skills.txt. Without either, Skills.txt cannot be filtered by
occupation and is skipped with a warning rather than imported unfiltered.

Skills.txt also holds two rows per occupation/skill pair - one on the
Importance scale (IM, 1-5) and one on Level (LV, 0-7). Importing both would
double every row, so only IM is used, and only above --min-importance: every
occupation carries a rating for every one of the ~35 skills, including those
that plainly do not apply, so an unfiltered import would assert that Software
Developers need "Negotiation" as much as "Programming".

Usage:
    python fetch_and_import_onet.py --dry-run     # preview, no DB writes
    python fetch_and_import_onet.py
    python fetch_and_import_onet.py --truncate    # replace existing rows
    python fetch_and_import_onet.py --min-importance 3.5

Requires: psycopg2-binary, python-dotenv (see database/requirements.txt)
Reads DB connection settings from database/.env (see .env.example).
"""

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = SCRIPT_DIR / "onet_raw"

TECH_SKILLS_FILE = "Technology Skills.txt"
SKILLS_FILE = "Skills.txt"
OCCUPATION_FILE = "Occupation Data.txt"

# Matched as case-insensitive substrings, not exact equality: O*NET retitles
# occupations between taxonomy releases ("Database Administrators" became
# "Database Administrators and Architects"), and exact matching would silently
# drop a whole occupation the moment that happens.
TARGET_OCCUPATIONS = [
    "Software Developers",
    "Data Scientists",
    "Computer Systems Analysts",
    "Web Developers",
    "Database Administrators",
    "DevOps Engineers",
]

# Importance ratings run 1-5. 3.0 ("important") is the cut: below it O*NET is
# recording that a skill is largely irrelevant to the occupation, which is the
# opposite of what a job-demand reference table should assert.
DEFAULT_MIN_IMPORTANCE = 3.0
IMPORTANCE_SCALE_ID = "IM"

# O*NET groups skills by Element ID prefix; keeping that structure gives
# job_skills.skill_category something meaningful instead of one flat label.
SKILL_CATEGORIES = {
    "2.A.1": "Basic Skills: Content",
    "2.A.2": "Basic Skills: Process",
    "2.B.1": "Cross-Functional: Social Skills",
    "2.B.2": "Cross-Functional: Complex Problem Solving",
    "2.B.3": "Cross-Functional: Technical Skills",
    "2.B.4": "Cross-Functional: Systems Skills",
    "2.B.5": "Cross-Functional: Resource Management",
}


class DataFileError(RuntimeError):
    """A source file is missing, unreadable, or not shaped as expected."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_tsv(path: Path, required_columns: set) -> list:
    """
    Read a tab-delimited O*NET export into a list of dicts.

    O*NET has shipped these files with differing encodings between releases,
    so UTF-8 (with or without BOM) is tried first and Latin-1 used as a
    fallback rather than letting one stray byte abort the whole import.
    """
    if not path.exists():
        raise DataFileError(f"File not found: {path}")

    last_error = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            with path.open(encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t")
                fieldnames = {name.strip() for name in (reader.fieldnames or [])}

                missing = required_columns - fieldnames
                if missing:
                    found = ", ".join(sorted(fieldnames)) or "(none)"
                    raise DataFileError(
                        f"{path.name} is missing expected column(s): "
                        f"{', '.join(sorted(missing))}.\n"
                        f"    Found: {found}\n"
                        f"    Is this the tab-delimited O*NET export?"
                    )

                return [
                    {(key.strip() if key else key): value for key, value in row.items()}
                    for row in reader
                ]
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    raise DataFileError(f"Could not decode {path.name}: {last_error}")


def is_target_occupation(title: str) -> bool:
    title_lower = (title or "").lower()
    return any(target.lower() in title_lower for target in TARGET_OCCUPATIONS)


def clean(value: str) -> str:
    """Collapse whitespace and strip stray quoting O*NET sometimes leaves behind."""
    return " ".join((value or "").split()).strip().strip('"').strip()


# ---------------------------------------------------------------------------
# Extraction per source file
# ---------------------------------------------------------------------------

def load_occupation_titles(raw_dir: Path) -> dict:
    """
    Build the SOC code -> occupation title map that Skills.txt needs.

    Prefers Occupation Data.txt, the file whose job this is. Falls back to the
    mapping implied by Technology Skills.txt, which carries both fields.
    Returns {} when neither is available.
    """
    for filename in (OCCUPATION_FILE, TECH_SKILLS_FILE):
        path = raw_dir / filename
        if not path.exists():
            continue
        rows = read_tsv(path, {"O*NET-SOC Code", "Title"})
        return {
            clean(row["O*NET-SOC Code"]): clean(row["Title"])
            for row in rows
            if row.get("O*NET-SOC Code")
        }

    return {}


def extract_technology_skills(raw_dir: Path, stats: Counter) -> list:
    """Rows from Technology Skills.txt as (occupation_title, skill_name, category)."""
    rows = read_tsv(raw_dir / TECH_SKILLS_FILE, {"Title", "Example"})
    stats["tech_rows_read"] = len(rows)

    extracted = []
    for row in rows:
        title = clean(row.get("Title"))
        if not is_target_occupation(title):
            continue

        skill_name = clean(row.get("Example"))
        if not skill_name:
            stats["tech_blank_skill"] += 1
            continue

        category = clean(row.get("Commodity Title")) or "Technology Skill"
        extracted.append((title, skill_name, category))

    stats["tech_rows_kept"] = len(extracted)
    return extracted


def extract_worker_skills(raw_dir: Path, min_importance: float, stats: Counter) -> list:
    """Rows from Skills.txt as (occupation_title, skill_name, category)."""
    path = raw_dir / SKILLS_FILE
    if not path.exists():
        stats["skills_missing"] = 1
        return []

    titles_by_code = load_occupation_titles(raw_dir)
    if not titles_by_code:
        print(
            f"  WARNING: {SKILLS_FILE} has no Title column, and neither {OCCUPATION_FILE}\n"
            f"           nor {TECH_SKILLS_FILE} was available to resolve SOC codes to\n"
            f"           occupation names. Skipping it rather than importing every occupation.",
            file=sys.stderr,
        )
        stats["skills_unresolvable"] = 1
        return []

    rows = read_tsv(
        path, {"O*NET-SOC Code", "Element ID", "Element Name", "Scale ID", "Data Value"}
    )
    stats["skills_rows_read"] = len(rows)

    extracted = []
    for row in rows:
        # Only the Importance scale; Level rows measure the same pairs
        # differently and would duplicate every entry.
        if clean(row.get("Scale ID")) != IMPORTANCE_SCALE_ID:
            continue
        stats["skills_importance_rows"] += 1

        title = titles_by_code.get(clean(row.get("O*NET-SOC Code")), "")
        if not is_target_occupation(title):
            continue

        # O*NET flags estimates it considers unreliable or inapplicable.
        if clean(row.get("Recommend Suppress")).upper() == "Y":
            stats["skills_suppressed"] += 1
            continue
        if clean(row.get("Not Relevant")).upper() == "Y":
            stats["skills_not_relevant"] += 1
            continue

        try:
            importance = float(clean(row.get("Data Value")))
        except (TypeError, ValueError):
            stats["skills_bad_value"] += 1
            continue

        if importance < min_importance:
            stats["skills_below_threshold"] += 1
            continue

        skill_name = clean(row.get("Element Name"))
        if not skill_name:
            stats["skills_blank_name"] += 1
            continue

        element_id = clean(row.get("Element ID"))
        category = SKILL_CATEGORIES.get(element_id[:5], "O*NET Skill")
        extracted.append((title, skill_name, category))

    stats["skills_rows_kept"] = len(extracted)
    return extracted


def deduplicate(rows: list, stats: Counter) -> list:
    """
    Collapse rows that would collide on job_skills' UNIQUE (occupation_title,
    skill_name) constraint, keeping the first category seen.

    The same skill legitimately appears many times in Technology Skills.txt
    under different commodity groupings, and can appear in both source files.
    """
    seen = {}
    for title, skill_name, category in rows:
        key = (title.lower(), skill_name.lower())
        if key in seen:
            stats["duplicates_collapsed"] += 1
            continue
        seen[key] = (title, skill_name, category)
    return list(seen.values())


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def database_dsn() -> str:
    """DATABASE_URL if set, else composed from POSTGRES_* (see .env.example)."""
    load_dotenv(dotenv_path=SCRIPT_DIR / ".env")

    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "curriculum_portal")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def import_rows(rows: list, truncate: bool) -> tuple:
    """
    Insert rows into job_skills. Returns (inserted, skipped, total_after).

    ON CONFLICT DO NOTHING makes a re-run idempotent without diffing existing
    rows in application code - Postgres already does that check at the
    constraint level, with no race between the "does it exist" read and the
    insert. RETURNING lets us count what actually landed, so the number
    reported is inserts rather than attempts.
    """
    dsn = database_dsn()
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        raise DataFileError(f"Could not connect to the database at {dsn}: {exc}") from exc

    try:
        with conn, conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE job_skills RESTART IDENTITY;")
                print("  Truncated job_skills.")

            returned = execute_values(
                cur,
                "INSERT INTO job_skills (occupation_title, skill_name, skill_category) VALUES %s "
                "ON CONFLICT (occupation_title, skill_name) DO NOTHING RETURNING id",
                rows,
                fetch=True,
            )
            inserted = len(returned)

            cur.execute("SELECT COUNT(*) FROM job_skills;")
            total_after = cur.fetchone()[0]
    finally:
        conn.close()

    return inserted, len(rows) - inserted, total_after


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def report_occupations(rows: list) -> None:
    """Per-occupation counts, so an unmatched target is visible rather than silent."""
    counts = Counter(title for title, _, _ in rows)

    print("\n  Rows per occupation:")
    matched_targets = set()
    for title, count in sorted(counts.items()):
        print(f"    {count:5}  {title}")
        for target in TARGET_OCCUPATIONS:
            if target.lower() in title.lower():
                matched_targets.add(target)

    unmatched = [t for t in TARGET_OCCUPATIONS if t not in matched_targets]
    if unmatched:
        print("\n  WARNING: no O*NET occupation matched these targets:")
        for target in unmatched:
            print(f"    - {target}")
        print("    Either the title changed in this O*NET release, or the occupation")
        print("    does not exist in the SOC taxonomy. Check TARGET_OCCUPATIONS.")


def preview(rows: list, limit: int = 15) -> None:
    shown = min(limit, len(rows))
    print(f"\n  Sample of {shown} rows:")
    print(f"    {'occupation_title':38} {'skill_name':32} skill_category")
    print(f"    {'-' * 38} {'-' * 32} {'-' * 28}")
    for title, skill_name, category in rows[:limit]:
        print(f"    {title[:37]:38} {skill_name[:31]:32} {category[:28]}")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import O*NET technology and worker skills into the job_skills table."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=DEFAULT_RAW_DIR,
        help=f"Directory holding the O*NET exports (default: {DEFAULT_RAW_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, filter, and report what would be imported without touching the database.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Empty job_skills before inserting (use to replace a stale import).",
    )
    parser.add_argument(
        "--min-importance",
        type=float,
        default=DEFAULT_MIN_IMPORTANCE,
        help=(
            "Minimum O*NET importance rating, 1-5, for Skills.txt rows "
            f"(default: {DEFAULT_MIN_IMPORTANCE})."
        ),
    )
    parser.add_argument(
        "--skip-skills",
        action="store_true",
        help=f"Import only {TECH_SKILLS_FILE}, ignoring {SKILLS_FILE}.",
    )
    args = parser.parse_args()

    raw_dir = args.raw_dir.resolve()
    print(f"Reading O*NET exports from {raw_dir}")

    if not raw_dir.is_dir():
        sys.exit(
            f"\nERROR: {raw_dir} does not exist.\n\n"
            f"Download the tab-delimited O*NET database from\n"
            f"  https://www.onetcenter.org/database.html\n"
            f"and place these files in that directory:\n"
            f"  {TECH_SKILLS_FILE}   (required)\n"
            f"  {SKILLS_FILE}                (optional, adds worker-requirement skills)\n"
            f"  {OCCUPATION_FILE}       (optional, resolves SOC codes for {SKILLS_FILE})"
        )

    stats = Counter()
    try:
        tech_rows = extract_technology_skills(raw_dir, stats)
        skill_rows = (
            [] if args.skip_skills else extract_worker_skills(raw_dir, args.min_importance, stats)
        )
    except DataFileError as exc:
        sys.exit(f"\nERROR: {exc}")

    print(
        f"\n  {TECH_SKILLS_FILE}: {stats['tech_rows_read']} rows read, "
        f"{stats['tech_rows_kept']} kept after occupation filter"
    )

    if args.skip_skills:
        print(f"  {SKILLS_FILE}: skipped (--skip-skills)")
    elif stats["skills_missing"]:
        print(f"  {SKILLS_FILE}: not found in {raw_dir.name}/ - importing technology skills only")
    elif not stats["skills_unresolvable"]:
        print(
            f"  {SKILLS_FILE}: {stats['skills_rows_read']} rows read, "
            f"{stats['skills_importance_rows']} on the {IMPORTANCE_SCALE_ID} scale, "
            f"{stats['skills_rows_kept']} kept at importance >= {args.min_importance}"
        )
        for count, reason in (
            (stats["skills_below_threshold"], "below the importance threshold"),
            (stats["skills_suppressed"], "flagged Recommend Suppress"),
            (stats["skills_not_relevant"], "flagged Not Relevant"),
            (stats["skills_bad_value"], "with an unparseable Data Value"),
        ):
            if count:
                print(f"      dropped {count} rows {reason}")

    combined = deduplicate(tech_rows + skill_rows, stats)
    if stats["duplicates_collapsed"]:
        print(
            f"\n  Collapsed {stats['duplicates_collapsed']} duplicate "
            f"(occupation, skill) pairs"
        )

    if not combined:
        sys.exit(
            "\nERROR: no rows survived filtering - nothing to import.\n"
            "       Check that the files cover the occupations in TARGET_OCCUPATIONS."
        )

    print(f"\n  {len(combined)} unique (occupation, skill) rows ready")
    report_occupations(combined)

    if args.dry_run:
        preview(combined)
        print(f"\nDRY RUN: {len(combined)} rows would be imported. Database not modified.")
        print("Re-run without --dry-run to commit.")
        return

    try:
        inserted, skipped, total_after = import_rows(combined, args.truncate)
    except DataFileError as exc:
        sys.exit(f"\nERROR: {exc}")

    print(
        f"\nImported {inserted} rows into job_skills "
        f"({skipped} already present, skipped). Table now holds {total_after}."
    )


if __name__ == "__main__":
    main()
