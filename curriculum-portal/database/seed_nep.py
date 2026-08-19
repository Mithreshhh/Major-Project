"""
seed_nep.py

Populates the `nep_competencies` table (see schema.sql) with a starter set of
National Education Policy 2020 competencies, so the nlp-engine's /analyze
endpoint can score a syllabus's NEP alignment.

This is a *reference set*, not an official NEP export — NEP 2020 describes its
competencies in prose, not as a downloadable taxonomy the way O*NET publishes
job skills. The phrases below are drawn from the policy's recurring themes
(holistic and multidisciplinary education, critical thinking, digital and
computational literacy, vocational exposure, Indian knowledge systems,
environmental awareness, ethics and constitutional values). Treat it as a
sensible default to replace with your institution's own mapping once you have
one — nothing else in the codebase hardcodes these strings.

Usage:
    python seed_nep.py
    python seed_nep.py --truncate      # replace the existing set

Requires: psycopg2-binary, python-dotenv (see database/requirements.txt)
Reads DB connection settings from database/.env (see .env.example).
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/curriculum_portal"
)

# (competency_name, description, category)
NEP_COMPETENCIES = [
    (
        "Critical thinking and problem solving",
        "Analyzing problems, evaluating evidence, and reasoning to a solution rather than recalling facts.",
        "Higher-order thinking",
    ),
    (
        "Computational thinking",
        "Decomposing problems, recognizing patterns, and expressing solutions as algorithms.",
        "Higher-order thinking",
    ),
    (
        "Digital literacy",
        "Using digital tools, platforms, and data responsibly and effectively.",
        "Digital and technological",
    ),
    (
        "Coding and programming",
        "Writing, reading, and debugging code in at least one programming language.",
        "Digital and technological",
    ),
    (
        "Data literacy and quantitative reasoning",
        "Interpreting data, applying statistical reasoning, and drawing defensible conclusions from it.",
        "Digital and technological",
    ),
    (
        "Scientific temper and evidence-based reasoning",
        "Approaching claims with inquiry, scepticism, and a demand for evidence.",
        "Higher-order thinking",
    ),
    (
        "Creativity and innovation",
        "Generating original ideas and applying them to novel problems.",
        "Higher-order thinking",
    ),
    (
        "Communication skills",
        "Expressing ideas clearly in writing and speech to technical and non-technical audiences.",
        "Communication and collaboration",
    ),
    (
        "Collaboration and teamwork",
        "Working effectively in teams, including across disciplines.",
        "Communication and collaboration",
    ),
    (
        "Multilingualism and language proficiency",
        "Competence in more than one language, including the mother tongue or a regional language.",
        "Communication and collaboration",
    ),
    (
        "Ethical reasoning and constitutional values",
        "Applying ethical judgement and constitutional values such as justice, liberty, and equality.",
        "Values and ethics",
    ),
    (
        "Environmental awareness and sustainability",
        "Understanding environmental systems, climate impact, and sustainable practice.",
        "Values and ethics",
    ),
    (
        "Health, well-being and physical education",
        "Knowledge and habits supporting physical and mental well-being.",
        "Holistic development",
    ),
    (
        "Indian knowledge systems and cultural rootedness",
        "Engagement with India's intellectual, artistic, and cultural traditions.",
        "Holistic development",
    ),
    (
        "Multidisciplinary and holistic learning",
        "Connecting concepts across disciplines rather than treating subjects in isolation.",
        "Holistic development",
    ),
    (
        "Vocational skills and hands-on experience",
        "Practical, applied skills gained through internships, labs, projects, or fieldwork.",
        "Employability",
    ),
    (
        "Research and inquiry skills",
        "Formulating research questions, reviewing literature, and conducting independent investigation.",
        "Employability",
    ),
    (
        "Entrepreneurship and financial literacy",
        "Understanding enterprise, opportunity assessment, and personal or organizational finance.",
        "Employability",
    ),
    (
        "Professional ethics and social responsibility",
        "Recognizing professional obligations and the social consequences of one's work.",
        "Values and ethics",
    ),
    (
        "Lifelong learning and adaptability",
        "Self-directed learning and the capacity to re-skill as fields change.",
        "Holistic development",
    ),
]


def seed(truncate: bool = False) -> None:
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except psycopg2.OperationalError as exc:
        sys.exit(f"Could not connect to the database at {DATABASE_URL}: {exc}")

    try:
        with conn, conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE nep_competencies RESTART IDENTITY;")
                print("Truncated nep_competencies.")

            # No unique constraint exists on competency_name (see schema.sql),
            # so re-running would otherwise duplicate rows. Filter against
            # what's already there instead of blindly inserting.
            cur.execute("SELECT competency_name FROM nep_competencies;")
            existing = {row[0].strip().lower() for row in cur.fetchall() if row[0]}

            new_rows = [row for row in NEP_COMPETENCIES if row[0].strip().lower() not in existing]
            skipped = len(NEP_COMPETENCIES) - len(new_rows)

            if new_rows:
                execute_values(
                    cur,
                    "INSERT INTO nep_competencies (competency_name, description, category) VALUES %s",
                    new_rows,
                )

            cur.execute("SELECT COUNT(*) FROM nep_competencies;")
            total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Inserted {len(new_rows)} competencies ({skipped} already present). Table now holds {total}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the nep_competencies reference table.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Empty nep_competencies before inserting (use to replace an edited set).",
    )
    args = parser.parse_args()
    seed(truncate=args.truncate)


if __name__ == "__main__":
    main()
