"""
seed_nep.py

Populates the `nep_competencies` table (see schema.sql) with the competency
set the nlp-engine scores syllabi against for NEP alignment.

SOURCE
------
Every competency below is drawn from Part II (Higher Education) of the
National Education Policy 2020 - sections 9-19 of the official document,
extracted to:

    nlp-engine/data/nep_2020_higher_education.txt

by `extract_nep_chapter.py`. Each entry cites the policy paragraph it comes
from, and those citations are checked against the extracted text at seed
time (see verify_citations) so the set can't silently drift from its source.

WHAT COUNTS AS A COMPETENCY HERE
--------------------------------
The policy paragraphs on flexible curricula and credit systems (11.5, 11.9,
12.2, 16.8) describe *structural* provisions - the Academic Bank of Credit,
multiple entry/exit points, the 4-year multidisciplinary degree, criterion-
based grading. Those are the source of several competencies below but are
not themselves listed as rows, because a syllabus cannot "cover" the
Academic Bank of Credit: scoring against it would guarantee a permanently
unmatched row and depress the NEP score without meaning anything. What those
paragraphs *do* yield is curriculum-visible capability - multidisciplinary
breadth, disciplinary depth, research project experience, lifelong learning,
credit-bearing internships - and those are what appear here.

Competency names are kept as concrete as the policy's own wording allows.
Matching is by sentence embedding against short syllabus phrases, so an
abstract name ("Critical thinking and problem solving") matches measurably
worse than a concrete one - see SKILL.md section 4.

SCOPE BOUNDARY
--------------
This is Part II only. Digital literacy and technology integration are NEP
competencies, but they live in sections 23-24 (Part III), outside the Higher
Education chapter, so they are deliberately absent rather than invented. To
include them, extend extract_nep_chapter.py to cover Part III and add the
rows here with their citations.

Usage:
    python seed_nep.py
    python seed_nep.py --truncate      # replace the existing set

Requires: psycopg2-binary, python-dotenv (see database/requirements.txt)
Reads DB connection settings from database/.env (see .env.example).
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


def database_url() -> str:
    """
    Resolve the connection string, accepting either convention.

    DATABASE_URL wins if set, because that's what backend/.env and
    nlp-engine/.env use and a single value is harder to get half-wrong.
    Otherwise it's composed from the POSTGRES_* variables that
    database/.env.example and import_onet.py already use, so both scripts in
    this directory can share one .env.
    """
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    name = os.getenv("POSTGRES_DB", "curriculum_portal")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


SOURCE_TEXT = (
    Path(__file__).resolve().parent.parent / "nlp-engine" / "data" / "nep_2020_higher_education.txt"
)

# (competency_name, description, category, source paragraph in NEP 2020 Part II)
NEP_COMPETENCIES = [
    # --- Higher-order thinking (9.1.1, 11.2) --------------------------------
    (
        "Critical thinking",
        "Critical thinking and higher-order thinking capacities, which the policy cites as a "
        "measured outcome of integrating the humanities and arts with STEM.",
        "Higher-order thinking",
        "11.2",
    ),
    (
        "Problem solving",
        "Problem-solving abilities developed through holistic and multidisciplinary study.",
        "Higher-order thinking",
        "11.2",
    ),
    (
        "Creativity and innovation",
        "Increased creativity and innovation; the policy sets out to develop 'good, thoughtful, "
        "well-rounded, and creative individuals'.",
        "Higher-order thinking",
        "11.2",
    ),
    (
        "Scientific temper",
        "Scientific temper, named both as a 21st century capability and as a universal human "
        "value to be developed through value-based education.",
        "Higher-order thinking",
        "9.1.1",
    ),
    (
        "Intellectual curiosity",
        "Intellectual curiosity, listed among the capabilities quality higher education must "
        "develop alongside character and creativity.",
        "Higher-order thinking",
        "9.1.1",
    ),
    (
        "Analytical reasoning",
        "Analytic capability, developed by making students well-rounded across artistic, "
        "creative, and analytic subjects.",
        "Higher-order thinking",
        "10.1",
    ),
    # --- Multidisciplinary breadth and depth (10, 11) -----------------------
    (
        "Multidisciplinary breadth",
        "Capacities across the arts, humanities, languages, sciences, social sciences, and "
        "professional, technical, and vocational fields, developed in an integrated manner.",
        "Holistic and multidisciplinary education",
        "11.3",
    ),
    (
        "Interdisciplinary thinking",
        "Cross-disciplinary and interdisciplinary thinking, which the policy makes an explicit "
        "emphasis of pedagogy alongside communication, discussion, debate, and research.",
        "Holistic and multidisciplinary education",
        "11.6",
    ),
    (
        "Integration of humanities and arts with STEM",
        "Undergraduate education that integrates the humanities and arts with Science, "
        "Technology, Engineering and Mathematics, shown to improve learning outcomes.",
        "Holistic and multidisciplinary education",
        "11.2",
    ),
    (
        "Disciplinary depth and specialization",
        "Rigorous specialization in a chosen field or fields, studied at a deep level - the "
        "counterweight the policy pairs with multidisciplinary breadth.",
        "Holistic and multidisciplinary education",
        "11.3",
    ),
    (
        "Aesthetic and artistic capacities",
        "The aesthetic capacities among the intellectual, aesthetic, social, physical, "
        "emotional, and moral capacities a holistic education aims to develop.",
        "Holistic and multidisciplinary education",
        "11.3",
    ),
    (
        "Mastery of curricula across fields",
        "In-depth learning and mastery of curricula across fields, rather than early "
        "specialisation into narrow areas of study.",
        "Holistic and multidisciplinary education",
        "11.2",
    ),
    # --- Communication and collaboration (11.2, 11.3, 11.6, 11.7) -----------
    (
        "Communication skills",
        "Communication skills, named both as a measured outcome of multidisciplinary study and "
        "as a soft skill a holistic education must develop.",
        "Communication and collaboration",
        "11.2",
    ),
    (
        "Discussion and debate",
        "Discussion and debate, listed among the soft skills a holistic education develops and "
        "among the pedagogical emphases of multidisciplinary institutions.",
        "Communication and collaboration",
        "11.3",
    ),
    (
        "Teamwork and collaboration",
        "Teamwork, cited as a measured learning outcome of integrating the humanities and arts "
        "with STEM.",
        "Communication and collaboration",
        "11.2",
    ),
    (
        "Language and literature studies",
        "Study in Languages, Literature, and Translation and Interpretation, among the "
        "departments to be established and strengthened at all HEIs.",
        "Communication and collaboration",
        "11.7",
    ),
    # --- Values, ethics and citizenship (9.1.1, 11.2, 11.8) -----------------
    (
        "Ethical reasoning",
        "Ethical values, developed through value-based education covering humanistic, ethical, "
        "Constitutional, and universal human values.",
        "Values and ethics",
        "11.8",
    ),
    (
        "Constitutional values and citizenship",
        "Constitutional values and citizenship values, including truth, righteous conduct, "
        "peace, love, and non-violence.",
        "Values and ethics",
        "11.8",
    ),
    (
        "Social and moral awareness",
        "Increases in social and moral awareness, cited as an outcome of integrating the "
        "humanities and arts with STEM.",
        "Values and ethics",
        "11.2",
    ),
    (
        "Community engagement and service",
        "Credit-based courses and projects in community engagement and service; participation "
        "in community service programmes is an integral part of a holistic education.",
        "Values and ethics",
        "11.8",
    ),
    (
        "Life skills",
        "Life-skills, developed as part of the value-based education included in the flexible "
        "and innovative curricula of all HEIs.",
        "Values and ethics",
        "11.8",
    ),
    (
        "Character and ethical grounding",
        "Character development and sound ethical grounding, which the policy treats as critical "
        "to high-quality learning rather than incidental to it.",
        "Values and ethics",
        "9.1.1",
    ),
    # --- Environment and global citizenship (11.8) --------------------------
    (
        "Environmental education and sustainability",
        "Credit-based courses in environmental education, including sustainable development and "
        "living, waste management, sanitation, and pollution.",
        "Environment and global citizenship",
        "11.8",
    ),
    (
        "Climate change and biodiversity conservation",
        "Climate change, conservation of biological diversity, management of biological "
        "resources, and forest and wildlife conservation.",
        "Environment and global citizenship",
        "11.8",
    ),
    (
        "Global citizenship education",
        "Global Citizenship Education, empowering learners to understand global issues and "
        "promote peaceful, tolerant, inclusive, secure, and sustainable societies.",
        "Environment and global citizenship",
        "11.8",
    ),
    # --- Vocational skills and employability (11.8, 11.12, 16) --------------
    (
        "Vocational skills",
        "Quality vocational education integrated into higher education, with every learner "
        "gaining exposure to at least one vocation.",
        "Vocational and employability",
        "16.4",
    ),
    (
        "Internships and industry exposure",
        "Internships with local industry, businesses, artists, and crafts persons, so students "
        "engage with the practical side of their learning and improve their employability.",
        "Vocational and employability",
        "11.8",
    ),
    (
        "Soft skills",
        "Soft skills, offered through short-term certificate courses and developed as part of a "
        "holistic education.",
        "Vocational and employability",
        "16.5",
    ),
    (
        "Apprenticeship and practical training",
        "Different models of vocational education and apprenticeships, experimented with by "
        "higher education institutions in partnership with industry.",
        "Vocational and employability",
        "16.7",
    ),
    (
        "Entrepreneurship and start-up incubation",
        "Start-up incubation centres and industry-academia linkages, set up by HEIs to promote "
        "innovation among student communities.",
        "Vocational and employability",
        "11.12",
    ),
    (
        "Indian arts, artisanship and Lok Vidya",
        "'Lok Vidya' - vocational knowledge developed in India - and the Indian arts and "
        "artisanship whose dignity the policy sets out to restore.",
        "Vocational and employability",
        "16.5",
    ),
    # --- Research and innovation (11.6, 11.9, 11.12) ------------------------
    (
        "Research methods and inquiry",
        "Research as an explicit emphasis of pedagogy, and the rigorous research project that "
        "earns a 4-year Bachelor's degree 'with Research'.",
        "Research and innovation",
        "11.9",
    ),
    (
        "Technology development and application",
        "Technology development centres and centres in frontier areas of research, through "
        "which HEIs pursue research and innovation.",
        "Research and innovation",
        "11.12",
    ),
    # --- Lifelong learning and wellness (11.5, 12.1) ------------------------
    (
        "Lifelong learning",
        "Life-long learning, enabled by flexible curricular structures offering multiple entry "
        "and exit points and creative combinations of disciplines.",
        "Lifelong learning and wellness",
        "11.5",
    ),
    (
        "Physical fitness and health",
        "Fitness and good health, among the capacities promoting student wellness that the "
        "policy treats as critical to high-quality learning.",
        "Lifelong learning and wellness",
        "12.1",
    ),
    (
        "Psycho-social well-being",
        "Psycho-social well-being, supported by counselling systems for handling stress and "
        "emotional adjustment.",
        "Lifelong learning and wellness",
        "12.1",
    ),
    (
        "Sports and physical education",
        "Sports, among the subjects needed for a multidisciplinary education and among the "
        "activities of a vibrant campus life.",
        "Lifelong learning and wellness",
        "11.7",
    ),
]


def verify_citations() -> list:
    """
    Check every cited paragraph actually exists in the extracted chapter.

    Cheap insurance that this list stays tied to its source: if a citation is
    mistyped, or the extraction changes shape, that shows up here rather than
    as a competency nobody can trace back to the policy. Returns the list of
    citations that could not be found; an empty list means all are present.
    """
    if not SOURCE_TEXT.exists():
        return []

    text = SOURCE_TEXT.read_text(encoding="utf-8")
    present = set(re.findall(r"^(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\.", text, re.M))
    return sorted({c for *_, c in NEP_COMPETENCIES if c not in present})


def seed(truncate: bool = False) -> None:
    missing = verify_citations()
    if missing:
        print(f"WARNING: cited paragraphs not found in {SOURCE_TEXT.name}: {', '.join(missing)}")
        print("         Re-run extract_nep_chapter.py, or correct the citations in this file.")
    elif SOURCE_TEXT.exists():
        print(f"Verified all citations against {SOURCE_TEXT.name}.")
    else:
        print(f"NOTE: {SOURCE_TEXT} not found - skipping citation check.")
        print("      Run extract_nep_chapter.py to regenerate it from the policy PDF.")

    dsn = database_url()
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as exc:
        sys.exit(f"Could not connect to the database at {dsn}: {exc}")

    rows = [
        (name, f"{description} (NEP 2020, para {citation})", category)
        for name, description, category, citation in NEP_COMPETENCIES
    ]

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

            new_rows = [row for row in rows if row[0].strip().lower() not in existing]
            skipped = len(rows) - len(new_rows)

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
    parser = argparse.ArgumentParser(
        description="Seed nep_competencies from NEP 2020 Part II (Higher Education)."
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Empty nep_competencies before inserting (use to replace an earlier set).",
    )
    args = parser.parse_args()
    seed(truncate=args.truncate)


if __name__ == "__main__":
    main()
