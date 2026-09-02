"""
test_recommendations.py

Exercises the recommendation generator against realistic mock input - no
database, no NLP models, no network. Everything here is hand-written sample
data standing in for what /analyze will eventually supply.

Run it directly to see the generated recommendation text and the assertions:

    cd nlp-engine
    python tests/test_recommendations.py

Plain asserts and a __main__ block rather than a pytest suite, matching the
self-test style already used in app/matching_engine.py and
app/skill_extraction.py - pytest isn't a dependency of this service. The
test_* function names mean `pytest tests/` also works if it's ever added.
"""

import sys
from pathlib import Path

# Allow running as a plain script from anywhere, not just as a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.recommendations import (  # noqa: E402
    Category,
    Priority,
    format_recommendations,
    generate_recommendations,
    recommendations_to_dicts,
)

# ---------------------------------------------------------------------------
# Mock input - shaped exactly like the real pipeline's output
# ---------------------------------------------------------------------------

# Six missing job-market skills spanning the full importance range, so every
# priority band and phrasing template gets exercised.
MOCK_MISSING_SKILLS = [
    {"skill": "Cloud Computing", "importance": 4.6},
    {"skill": "DevOps", "importance": 4.1},
    {"skill": "Cybersecurity", "importance": 3.9},
    {"skill": "Containerization (Docker/Kubernetes)", "importance": 3.6},
    {"skill": "Technical Writing", "importance": 3.2},
    {"skill": "Project Estimation", "importance": 2.4},
]

# Five NEP competencies from "essentially absent" to "well covered".
MOCK_NEP_BREAKDOWN = {
    "Multidisciplinary Exposure": 45,
    "Skill-Based Outcomes": 30,
    "Ethical Reasoning": 18,
    "Environmental Awareness": 12,
    "Communication and Collaboration": 72,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_summary_leads_and_priority_tags_descend():
    """
    Ordering is by priority band first, then urgency within the band.

    The visible [CRITICAL]/[HIGH]/... tags must never go back up: an earlier
    revision sorted on raw urgency alone, which put a [HIGH] item below a
    [MODERATE] one - arithmetically fine, but it reads as a bug in a report.
    """
    from app.recommendations import PRIORITY_RANK

    recs = generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN)

    assert recs, "expected recommendations"
    assert recs[0].category is Category.SUMMARY, "summary must come first"

    body = recs[1:]
    ranks = [PRIORITY_RANK[r.priority] for r in body]
    assert ranks == sorted(ranks), f"priority tags must not go back up: {ranks}"

    print("PASS  summary leads, priority tags descend monotonically")


def test_urgency_descends_within_each_band():
    recs = generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN, include_summary=False)

    by_band = {}
    for rec in recs:
        by_band.setdefault(rec.priority, []).append(rec.urgency)

    for priority, urgencies in by_band.items():
        assert urgencies == sorted(urgencies, reverse=True), (
            f"{priority.value} band not sorted by urgency: {urgencies}"
        )

    # Cross-scale check: a 4.6/5 missing skill (urgency 9.2) outranks a
    # competency at 12% coverage (urgency 8.8). Both are CRITICAL, so the
    # continuous urgency is what separates them.
    assert "Cloud Computing" in recs[0].headline, f"got: {recs[0].headline}"
    assert "Environmental Awareness" in recs[1].headline, f"got: {recs[1].headline}"
    print("PASS  urgency descends within each band, cross-scale ranking holds")


def test_priority_bands_match_thresholds():
    recs = generate_recommendations(MOCK_MISSING_SKILLS, {}, include_summary=False)
    by_skill = {r.evidence["skill"]: r for r in recs}

    assert by_skill["Cloud Computing"].priority is Priority.CRITICAL  # 4.6 >= 4.0
    assert by_skill["Cybersecurity"].priority is Priority.HIGH        # 3.9 in [3.5, 4.0)
    assert by_skill["Technical Writing"].priority is Priority.MODERATE  # 3.2 in [3.0, 3.5)
    print("PASS  importance thresholds map to the right priority bands")


def test_low_urgency_items_are_filtered():
    """Project Estimation (2.4 -> urgency 4.8) survives the default cut; a
    genuinely marginal skill should not."""
    recs = generate_recommendations(
        [{"skill": "Marginal Skill", "importance": 0.5}], {}, include_summary=False
    )
    assert recs == [], "a 0.5/5 skill should fall below the default urgency floor"

    kept = generate_recommendations(
        [{"skill": "Marginal Skill", "importance": 0.5}],
        {},
        min_urgency=0,
        include_summary=False,
    )
    assert len(kept) == 1, "min_urgency=0 should keep everything"
    print("PASS  low-urgency items filtered by default, retained at min_urgency=0")


def test_well_covered_nep_is_ranked_last():
    recs = generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN, include_summary=False)
    nep_items = [r for r in recs if r.category is Category.NEP_ALIGNMENT]
    assert "Communication and Collaboration" in nep_items[-1].headline, (
        "the best-covered competency should rank last among NEP items"
    )
    print("PASS  well-covered NEP competency ranks last")


def test_input_variants_are_tolerated():
    """A bare string list and a name -> importance dict shouldn't crash."""
    from_strings = generate_recommendations(["Cloud Computing", "DevOps"], {}, include_summary=False)
    assert len(from_strings) == 2

    from_dict = generate_recommendations({"Cloud Computing": 4.2}, {}, include_summary=False)
    assert len(from_dict) == 1
    assert from_dict[0].evidence["importance"] == 4.2

    assert generate_recommendations(None, None) == [], "empty input yields no recommendations"
    print("PASS  alternate input shapes and empty input handled")


def test_output_is_json_serializable():
    import json

    payload = recommendations_to_dicts(
        generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN, limit=3)
    )
    # allow_nan=False is the point of this test: an earlier revision gave
    # the summary urgency=float('inf'), which json.dumps emits as the
    # invalid literal `Infinity` and strict parsers reject.
    encoded = json.dumps(payload, allow_nan=False)
    assert "Infinity" not in encoded
    assert all(isinstance(item["urgency"], float) for item in payload)
    assert payload[0]["category"] == "summary"
    print("PASS  output serializes cleanly to JSON")


def test_limit_caps_body_not_summary():
    recs = generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN, limit=4)
    body = [r for r in recs if r.category is not Category.SUMMARY]
    assert len(body) == 4, f"expected 4 body items, got {len(body)}"
    print("PASS  limit caps body items and keeps the summary")


def _preview() -> None:
    print("=" * 78)
    print("MOCK INPUT")
    print("=" * 78)
    print(f"\nmissing_skills ({len(MOCK_MISSING_SKILLS)}):")
    for entry in MOCK_MISSING_SKILLS:
        print(f"    {entry['importance']:.1f}/5   {entry['skill']}")
    print(f"\nnep_score_breakdown ({len(MOCK_NEP_BREAKDOWN)}):")
    for name, score in MOCK_NEP_BREAKDOWN.items():
        print(f"    {score:3}%     {name}")

    print()
    print("=" * 78)
    print("GENERATED RECOMMENDATIONS")
    print("=" * 78)
    print()
    print(format_recommendations(generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN)))

    print()
    print("=" * 78)
    print("TOP 3 ONLY (limit=3)")
    print("=" * 78)
    print()
    print(
        format_recommendations(
            generate_recommendations(MOCK_MISSING_SKILLS, MOCK_NEP_BREAKDOWN, limit=3)
        )
    )


if __name__ == "__main__":
    _preview()

    print()
    print("=" * 78)
    print("ASSERTIONS")
    print("=" * 78)
    print()
    test_summary_leads_and_priority_tags_descend()
    test_urgency_descends_within_each_band()
    test_priority_bands_match_thresholds()
    test_low_urgency_items_are_filtered()
    test_well_covered_nep_is_ranked_last()
    test_input_variants_are_tolerated()
    test_output_is_json_serializable()
    test_limit_caps_body_not_summary()
    print("\nAll checks passed.")
