"""
extract_nep_chapter.py

Extracts Part II (Higher Education) from the National Education Policy 2020
PDF into a clean plain-text file, which is the source `seed_nep.py` derives
the `nep_competencies` reference set from.

Part II is sections 9-19 (printed pages 33-49):

     9. Quality Universities and Colleges
    10. Institutional Restructuring and Consolidation
    11. Towards a More Holistic and Multidisciplinary Education
    12. Optimal Learning Environments and Support for Students
    13. Motivated, Energized and Capable Faculty
    14. Equity and Inclusion in Higher Education
    15. Teacher Education
    16. Re-imagining Vocational Education
    17. Catalyzing Quality Academic Research (National Research Foundation)
    18. Transforming the Regulatory System of Higher Education
    19. Effective Governance and Leadership for HEIs

The chapter boundary is found by locating the section-20 heading
("Professional Education", the first section of Part III) rather than by
hardcoding a page count, so the extraction survives a repaginated release of
the PDF.

Cleaning applied:
  - the running header ("National Education Policy 2020" + page number) and
    footers are dropped
  - hard line wraps are unwrapped, so each numbered clause (e.g. "11.9.")
    becomes one paragraph that greps and reads as a unit
  - typographic quotes and en-dashes are folded to ASCII

Usage:
    python extract_nep_chapter.py                       # uses default paths
    python extract_nep_chapter.py --pdf path/to.pdf --out path/to.txt

Requires: pymupdf (see database/requirements.txt)
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pymupdf < 1.24.3 only exposed the legacy name
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("pymupdf is not installed. Run: pip install -r requirements.txt")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PDF = REPO_ROOT / "NEP_Final_English_0.pdf"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "nlp-engine" / "data" / "nep_2020_higher_education.txt"

# Part II opens with section 9 and ends where section 20 (Part III) begins.
START_HEADING = re.compile(r"^\s*9\.\s+Quality Universities and Colleges", re.M)
END_HEADING = re.compile(r"^\s*20\.\s+Professional Education", re.M)
PART_III_BANNER = re.compile(r"\s*Part\s+III\.\s*OTHER KEY AREAS OF FOCUS\s*$", re.I)

# Running header: "National Education Policy 2020" followed by a page number.
RUNNING_HEADER = re.compile(r"^\s*National Education Policy 2020\s*$", re.M)
PAGE_NUMBER_ONLY = re.compile(r"^\s*\d{1,3}\s*$")

# A new paragraph starts at a numbered clause ("11.9.") or a section heading
# ("11. Towards a More ..."). Everything else is a continuation line.
PARAGRAPH_START = re.compile(r"^(?:\d{1,2}\.\d{1,2}\.|\d{1,2}\.\s+[A-Z])")

ASCII_FOLD = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    " ": " ",
}


def fold_to_ascii(text: str) -> str:
    for source, replacement in ASCII_FOLD.items():
        text = text.replace(source, replacement)
    return text


def page_lines(page) -> list:
    """Return a page's lines with running headers and bare page numbers removed."""
    kept = []
    for raw in page.get_text().split("\n"):
        line = fold_to_ascii(raw).rstrip()
        if not line.strip():
            continue
        if RUNNING_HEADER.match(line) or PAGE_NUMBER_ONLY.match(line):
            continue
        kept.append(line.strip())
    return kept


def unwrap(lines: list) -> list:
    """
    Rejoin hard-wrapped lines into whole paragraphs.

    The PDF wraps mid-sentence, so a line break carries no meaning except
    where a new numbered clause begins. Joining on that rule keeps each
    policy clause on one line, which is what makes the output greppable.
    """
    paragraphs = []
    current = ""
    for line in lines:
        if PARAGRAPH_START.match(line):
            if current:
                paragraphs.append(current)
            current = line
        elif current:
            # A line ending in a hyphen is rejoined without a space, but the
            # hyphen is *kept*. Every such break in this chapter is a real
            # compound ("peer-reviewed", "well-being", "in-depth"), not a
            # soft hyphen from justification - dropping it would produce
            # "peerreviewed".
            current += line if current.endswith("-") else " " + line
        else:
            current = line
    if current:
        paragraphs.append(current)
    return [re.sub(r"\s{2,}", " ", p).strip() for p in paragraphs]


def extract(pdf_path: Path, out_path: Path) -> None:
    if not pdf_path.exists():
        sys.exit(f"PDF not found: {pdf_path}")

    doc = pymupdf.open(pdf_path)

    # Find the pages the chapter starts and ends on. Page 0-2 hold the table
    # of contents, whose entries would otherwise match the headings, so the
    # search starts past them.
    start_page = end_page = None
    for index in range(3, doc.page_count):
        text = fold_to_ascii(doc[index].get_text())
        if start_page is None and START_HEADING.search(text):
            start_page = index
        elif start_page is not None and END_HEADING.search(text):
            end_page = index
            break

    if start_page is None:
        sys.exit("Could not find the start of Part II (section 9) in this PDF.")
    if end_page is None:
        end_page = doc.page_count - 1

    lines = []
    for index in range(start_page, end_page + 1):
        lines.extend(page_lines(doc[index]))
    doc.close()

    paragraphs = unwrap(lines)

    # Trim to the exact chapter bounds: the start page carries the tail of
    # section 8, and the end page carries the head of section 20.
    first = next((i for i, p in enumerate(paragraphs) if START_HEADING.match(p)), 0)
    last = next((i for i, p in enumerate(paragraphs) if END_HEADING.match(p)), len(paragraphs))
    paragraphs = paragraphs[first:last]

    # The Part III banner sits inline ahead of the section-20 heading, so it
    # rides along on the tail of the last section-19 paragraph.
    if paragraphs:
        paragraphs[-1] = PART_III_BANNER.sub("", paragraphs[-1]).strip()

    header = [
        "National Education Policy 2020 - Part II: Higher Education (sections 9-19)",
        f"Extracted from {pdf_path.name} pages {start_page}-{end_page} by database/extract_nep_chapter.py.",
        "Source: Ministry of Education, Government of India. Reproduced for reference only.",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(header) + "\n\n".join(paragraphs) + "\n", encoding="utf-8")

    words = sum(len(p.split()) for p in paragraphs)
    print(f"Extracted {len(paragraphs)} paragraphs ({words} words) from pages {start_page}-{end_page}")
    print(f"Wrote {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract NEP 2020 Part II (Higher Education) to text.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help=f"Source PDF (default: {DEFAULT_PDF})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"Output text file (default: {DEFAULT_OUT})")
    args = parser.parse_args()
    extract(args.pdf, args.out)


if __name__ == "__main__":
    main()
