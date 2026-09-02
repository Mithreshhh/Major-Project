"""
recommendations.py

Turns a gap analysis into prioritized, readable curriculum recommendations.

Rule-based by design - no LLM call. The inputs are already numeric and the
output space is small and well understood, so templates give deterministic,
testable, instant, free output. An LLM here would add per-request cost and
latency, make the text non-reproducible between runs, and produce phrasing
nobody can review in advance - for a report an institution acts on, being
able to audit exactly what it will say is worth more than varied prose.

Inputs (both plain data - this module never touches the database):

    missing_skills: [{"skill": str, "importance": float}, ...]
        Job-market skills absent from the syllabus, with O*NET-style
        importance on a 1-5 scale.

    nep_score_breakdown: {competency_name: score_0_to_100, ...}
        Per-competency NEP alignment, higher = better covered.

Output: a list of Recommendation objects sorted most urgent first, each with
a headline, a body sentence explaining the evidence, and the numbers behind
it, so callers can render them as text, JSON, or HTML without re-deriving
anything.

Run this file directly for a self-test against sample input:
    python -m app.recommendations
"""

from dataclasses import dataclass, field, asdict
from enum import Enum

# --- Thresholds -------------------------------------------------------------
#
# Importance is O*NET's 1-5 scale: 4+ is "very important to extremely
# important" for the occupation, 3-4 is "important", below 3 the skill is
# marginal. Those breaks are the source's own semantics, not invented cutoffs.
IMPORTANCE_CRITICAL = 4.0
IMPORTANCE_HIGH = 3.5
IMPORTANCE_MODERATE = 3.0

# NEP coverage is a 0-100 percentage. A competency below 30 is effectively
# untaught; 30-60 is partial; above 60 is reasonable coverage that only
# warrants a note when something else is weaker.
NEP_CRITICAL = 30
NEP_PARTIAL = 60

# Recommendations below this urgency are dropped unless the caller asks for
# them - a report that lists everything prioritizes nothing.
DEFAULT_MIN_URGENCY = 2.0

# Top of the shared 0-10 urgency scale. The summary carries this value.
# It must stay finite: urgency is serialized to JSON, and float('inf')
# encodes as the literal `Infinity`, which strict JSON parsers reject.
MAX_URGENCY = 10.0


class Priority(str, Enum):
    """Human-facing urgency band. Ordered most to least urgent."""

    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


# Sort rank for the bands. Recommendations are ordered by band first and only
# then by urgency, so the printed [CRITICAL]/[HIGH]/... tags descend
# monotonically. Sorting on raw urgency alone interleaves them - a [HIGH] item
# landing below a [MODERATE] one is arithmetically fine and reads as a bug.
PRIORITY_RANK = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MODERATE: 2,
    Priority.LOW: 3,
}


class Category(str, Enum):
    """Which analysis produced a recommendation."""

    JOB_SKILL_GAP = "job_skill_gap"
    NEP_ALIGNMENT = "nep_alignment"
    SUMMARY = "summary"


@dataclass
class Recommendation:
    """
    One actionable suggestion.

    `urgency` is the sort key and is deliberately continuous rather than
    banded: two "critical" items still need a stable, meaningful order
    between them, which a four-value enum can't provide.
    """

    headline: str
    detail: str
    priority: Priority
    category: Category
    urgency: float
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["priority"] = self.priority.value
        data["category"] = self.category.value
        # Guard the JSON boundary: a non-finite urgency from any future
        # rule would otherwise serialize as `Infinity`/`NaN` and break
        # strict parsers.
        urgency = self.urgency
        if urgency != urgency or urgency in (float("inf"), float("-inf")):
            urgency = MAX_URGENCY
        data["urgency"] = round(urgency, 3)
        return data

    def as_text(self) -> str:
        return f"{self.headline} {self.detail}"


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------


def _normalize_missing_skills(missing_skills) -> list:
    """
    Accept the documented shape, and tolerate the obvious variants.

    Callers assemble this from several places (the NLP engine, a stored
    report, a test fixture), so a bare list of strings or a dict of
    name -> importance shouldn't be a crash. Anything genuinely unusable is
    skipped rather than guessed at.
    """
    if not missing_skills:
        return []

    if isinstance(missing_skills, dict):
        items = [{"skill": k, "importance": v} for k, v in missing_skills.items()]
    else:
        items = list(missing_skills)

    normalized = []
    for item in items:
        if isinstance(item, str):
            # No importance available: treat as moderate rather than
            # inventing a high score that would outrank measured ones.
            name, importance = item, IMPORTANCE_MODERATE
        elif isinstance(item, dict):
            name = item.get("skill") or item.get("name") or item.get("skill_name")
            importance = item.get("importance", item.get("score", IMPORTANCE_MODERATE))
        else:
            continue

        name = (name or "").strip()
        if not name:
            continue

        try:
            importance = float(importance)
        except (TypeError, ValueError):
            importance = IMPORTANCE_MODERATE

        normalized.append({"skill": name, "importance": importance})

    return normalized


def _normalize_nep(nep_score_breakdown) -> list:
    """Return [(competency, score)] with unusable entries dropped."""
    if not nep_score_breakdown:
        return []

    normalized = []
    for competency, score in dict(nep_score_breakdown).items():
        name = (competency or "").strip()
        if not name:
            continue
        try:
            normalized.append((name, float(score)))
        except (TypeError, ValueError):
            continue
    return normalized


# ---------------------------------------------------------------------------
# Phrasing helpers
# ---------------------------------------------------------------------------


def _importance_priority(importance: float) -> Priority:
    if importance >= IMPORTANCE_CRITICAL:
        return Priority.CRITICAL
    if importance >= IMPORTANCE_HIGH:
        return Priority.HIGH
    if importance >= IMPORTANCE_MODERATE:
        return Priority.MODERATE
    return Priority.LOW


def _nep_priority(score: float) -> Priority:
    if score < NEP_CRITICAL:
        return Priority.CRITICAL
    if score < NEP_PARTIAL:
        return Priority.HIGH
    return Priority.MODERATE


# Phrasing varies by band so the text carries the judgement, not just the
# number - "essentially absent" and "partially covered" read differently even
# before the reader looks at the score.
_SKILL_STRENGTH = {
    Priority.CRITICAL: "is rated among the most important skills",
    Priority.HIGH: "is rated highly important",
    Priority.MODERATE: "is rated important",
    Priority.LOW: "appears",
}

_SKILL_ACTION = {
    Priority.CRITICAL: "Add coverage for",
    Priority.HIGH: "Add coverage for",
    Priority.MODERATE: "Consider adding",
    Priority.LOW: "Optionally introduce",
}

_NEP_ACTION = {
    Priority.CRITICAL: "Strengthen",
    Priority.HIGH: "Build out",
    Priority.MODERATE: "Reinforce",
    Priority.LOW: "Maintain",
}

_NEP_STATE = {
    Priority.CRITICAL: "is essentially absent from the curriculum",
    Priority.HIGH: "is only partially covered",
    Priority.MODERATE: "is reasonably covered but has room to improve",
    Priority.LOW: "is well covered",
}

# The closing advice varies by band too. An earlier version ended every NEP
# recommendation with one identical sentence, which made a list of four read
# as a form letter and buried the difference between them.
_NEP_ADVICE = {
    Priority.CRITICAL: (
        "Introducing a credit-bearing course or project here would have the largest "
        "single effect on the institute's NEP alignment score."
    ),
    Priority.HIGH: (
        "Extending the existing coursework, or adding an assessed project component, "
        "would close most of the remaining gap."
    ),
    Priority.MODERATE: (
        "A single additional module or assessed activity would be enough to lift this further."
    ),
    Priority.LOW: "No action is needed here for now.",
}


def _plural(count: int, singular: str, plural: str = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _join_names(names: list, limit: int = 3) -> str:
    """Join names for prose: 'A, B and C', or 'A, B and 4 others' past the limit."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= limit:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    remaining = len(names) - limit
    return f"{', '.join(names[:limit])} and {remaining} {_plural(remaining, 'other')}"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _skill_recommendations(missing_skills: list) -> list:
    """One recommendation per missing job-market skill."""
    recommendations = []
    for entry in missing_skills:
        name = entry["skill"]
        importance = entry["importance"]
        priority = _importance_priority(importance)

        detail = (
            f"this skill {_SKILL_STRENGTH[priority]} across current job postings "
            f"({importance:.1f}/5) but is missing from the syllabus."
        )

        recommendations.append(
            Recommendation(
                headline=f"{_SKILL_ACTION[priority]}: {name} —",
                detail=detail,
                priority=priority,
                category=Category.JOB_SKILL_GAP,
                # Scaled to 0-10 against the 1-5 source scale, so job-skill and
                # NEP urgencies are directly comparable in one sorted list.
                urgency=importance * 2.0,
                evidence={"skill": name, "importance": round(importance, 2), "scale_max": 5},
            )
        )
    return recommendations


def _nep_recommendations(nep_scores: list) -> list:
    """One recommendation per under-covered NEP competency."""
    recommendations = []
    for competency, score in nep_scores:
        priority = _nep_priority(score)

        detail = (
            f"NEP alignment for this competency is {score:.0f}%, which means it "
            f"{_NEP_STATE[priority]}. {_NEP_ADVICE[priority]}"
        )

        recommendations.append(
            Recommendation(
                headline=f"{_NEP_ACTION[priority]} NEP competency: {competency} —",
                detail=detail,
                priority=priority,
                category=Category.NEP_ALIGNMENT,
                # Inverted: a lower coverage score is more urgent. Mapped onto
                # the same 0-10 range as skills so the two interleave sensibly.
                urgency=(100.0 - score) / 10.0,
                evidence={"competency": competency, "score": round(score, 1), "scale_max": 100},
            )
        )
    return recommendations


def _summary_recommendation(missing_skills: list, nep_scores: list) -> Recommendation:
    """
    A single opening line describing the shape of the problem.

    Pinned to the top by construction rather than by urgency, because it is
    context for the list rather than an item competing within it.
    """
    critical_skills = [s["skill"] for s in missing_skills if s["importance"] >= IMPORTANCE_CRITICAL]
    weak_nep = [c for c, score in nep_scores if score < NEP_CRITICAL]

    parts = []
    if critical_skills:
        parts.append(
            f"{len(critical_skills)} high-importance job {_plural(len(critical_skills), 'skill')} "
            f"missing ({_join_names(critical_skills)})"
        )
    if weak_nep:
        parts.append(
            f"{len(weak_nep)} NEP {_plural(len(weak_nep), 'competency', 'competencies')} "
            f"with minimal coverage ({_join_names(weak_nep)})"
        )

    if parts:
        headline = "Priority summary —"
        detail = f"This curriculum has {' and '.join(parts)}. Address these first."
    else:
        headline = "Priority summary —"
        detail = (
            "No critical gaps were found. The recommendations below are refinements "
            "rather than urgent corrections."
        )

    return Recommendation(
        headline=headline,
        detail=detail,
        priority=Priority.CRITICAL if parts else Priority.LOW,
        category=Category.SUMMARY,
        urgency=MAX_URGENCY,
        evidence={
            "critical_skill_count": len(critical_skills),
            "weak_nep_count": len(weak_nep),
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_recommendations(
    missing_skills=None,
    nep_score_breakdown=None,
    min_urgency: float = DEFAULT_MIN_URGENCY,
    limit: int = None,
    include_summary: bool = True,
) -> list:
    """
    Build a prioritized recommendation list from a gap analysis.

    Args:
        missing_skills: [{"skill": str, "importance": float}, ...] on a 1-5 scale.
        nep_score_breakdown: {competency: score} on a 0-100 scale.
        min_urgency: drop anything below this (0-10 scale). Pass 0 to keep all.
        limit: cap the number returned, after sorting. None for no cap.
        include_summary: prepend the summary line.

    Returns:
        [Recommendation] sorted most urgent first. The summary, when included,
        is always first.
    """
    skills = _normalize_missing_skills(missing_skills)
    nep_scores = _normalize_nep(nep_score_breakdown)

    if not skills and not nep_scores:
        return []

    items = _skill_recommendations(skills) + _nep_recommendations(nep_scores)
    items = [item for item in items if item.urgency >= min_urgency]

    # Band first, then urgency within the band, then category and name so the
    # order is fully deterministic - a report shouldn't reshuffle between two
    # identical runs. Category breaks ties toward job-skill gaps, which are
    # the more concrete action of the two.
    items.sort(key=lambda r: (PRIORITY_RANK[r.priority], -r.urgency, r.category.value, r.headline))

    if limit is not None:
        items = items[:limit]

    if include_summary:
        items.insert(0, _summary_recommendation(skills, nep_scores))

    return items


def format_recommendations(recommendations: list, width: int = 78) -> str:
    """Render recommendations as plain text, numbered and priority-tagged."""
    if not recommendations:
        return "No recommendations - no gaps were supplied."

    lines = []
    counter = 0
    for rec in recommendations:
        if rec.category is Category.SUMMARY:
            lines.append(f"{rec.headline} {rec.detail}")
            lines.append("")
            continue

        counter += 1
        tag = f"[{rec.priority.value.upper()}]"
        body = f"{counter}. {tag} {rec.headline} {rec.detail}"
        # Indent continuation lines to sit under the text, not the number -
        # which needs one more space once the count reaches double digits.
        lines.extend(_wrap(body, width, indent=" " * (len(str(counter)) + 2)))
        lines.append("")

    return "\n".join(lines).rstrip()


def _wrap(text: str, width: int, indent: str = "") -> list:
    """Minimal greedy word wrap - avoids a textwrap import for one call site."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        prefix = "" if not lines else indent
        if len(prefix) + len(candidate) > width and current:
            lines.append(f"{prefix}{current}")
            current = word
        else:
            current = candidate
    if current:
        lines.append(f"{'' if not lines else indent}{current}")
    return lines


def recommendations_to_dicts(recommendations: list) -> list:
    """JSON-serializable form, for returning over HTTP."""
    return [rec.to_dict() for rec in recommendations]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

SAMPLE_MISSING_SKILLS = [
    {"skill": "Cloud Computing", "importance": 4.2},
    {"skill": "DevOps", "importance": 3.8},
    {"skill": "Cybersecurity", "importance": 3.1},
]

SAMPLE_NEP_BREAKDOWN = {
    "Multidisciplinary Exposure": 45,
    "Skill-Based Outcomes": 30,
    "Ethical Reasoning": 18,
}


def _self_test() -> None:
    recs = generate_recommendations(SAMPLE_MISSING_SKILLS, SAMPLE_NEP_BREAKDOWN)
    print(format_recommendations(recs))

    assert recs[0].category is Category.SUMMARY, "summary should lead"
    body = recs[1:]

    # Band first: the printed [CRITICAL]/[HIGH]/... tags must never go back up.
    ranks = [PRIORITY_RANK[r.priority] for r in body]
    assert ranks == sorted(ranks), f"priority tags must not go back up: {ranks}"

    # Urgency descends within each band.
    for priority in {r.priority for r in body}:
        in_band = [r.urgency for r in body if r.priority is priority]
        assert in_band == sorted(in_band, reverse=True), f"{priority.value} band unsorted"

    assert all(r.urgency >= DEFAULT_MIN_URGENCY for r in body)

    print("\nSelf-test passed: summary leads, bands descend, urgency sorted within band.")


if __name__ == "__main__":
    _self_test()
