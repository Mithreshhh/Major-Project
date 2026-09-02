"""
evaluate.py

Measures the matching engine against a hand-labelled dataset: for each
(syllabus_skill, job_skill) pair with a known true/false match label, run the
pair through the real Sentence-BERT matcher and compare its verdict to the
label. Reports precision, recall, F1, and a confusion matrix.

This is what turns "0.6 seemed like a reasonable threshold" into a number.

INPUT
-----
A CSV with exactly these columns:

    syllabus_skill,job_skill,true_label

`true_label` accepts the obvious spellings of a boolean - 1/0, true/false,
yes/no, match/no_match - case-insensitive, so a dataset labelled by hand in a
spreadsheet doesn't need cleaning first.

Swapping the dummy data for a real labelled set is a file path, not a code
change:

    python evaluate.py --csv path/to/real_labels.csv

USAGE
-----
    python evaluate.py                          # runs against the bundled dummy set
    python evaluate.py --csv my_labels.csv
    python evaluate.py --threshold 0.5          # score at a different cut
    python evaluate.py --sweep                  # compare thresholds side by side
    python evaluate.py --show-errors            # list every misclassified pair

Requires the nlp-engine's normal dependencies (sentence-transformers); the
model loads once and scores every pair in a single batch.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.matching_engine import DEFAULT_SIMILARITY_THRESHOLD, compute_similarity_matrix  # noqa: E402

DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "eval_pairs_dummy.csv"
REQUIRED_COLUMNS = ("syllabus_skill", "job_skill", "true_label")

# Accepted spellings for the label column, so a spreadsheet-labelled file
# works without a cleaning pass first.
TRUE_VALUES = {"1", "true", "t", "yes", "y", "match"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "no_match", "nomatch"}

SWEEP_THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)


class EvaluationError(RuntimeError):
    """The labelled dataset is missing, malformed, or unusable."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def parse_label(raw: str, row_number: int) -> bool:
    value = (raw or "").strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise EvaluationError(
        f"Row {row_number}: could not read true_label={raw!r}. "
        f"Expected one of {sorted(TRUE_VALUES)} or {sorted(FALSE_VALUES)}."
    )


def load_pairs(csv_path: Path) -> list:
    """Read the labelled CSV into [{syllabus_skill, job_skill, true_label}]."""
    if not csv_path.exists():
        raise EvaluationError(
            f"Labelled dataset not found: {csv_path}\n"
            f"    Provide one with --csv, using the columns: {', '.join(REQUIRED_COLUMNS)}"
        )

    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = {name.strip() for name in (reader.fieldnames or [])}

        missing = set(REQUIRED_COLUMNS) - fieldnames
        if missing:
            raise EvaluationError(
                f"{csv_path.name} is missing column(s): {', '.join(sorted(missing))}.\n"
                f"    Found: {', '.join(sorted(fieldnames)) or '(none)'}\n"
                f"    Expected: {', '.join(REQUIRED_COLUMNS)}"
            )

        pairs = []
        for row_number, row in enumerate(reader, start=2):  # row 1 is the header
            syllabus_skill = (row.get("syllabus_skill") or "").strip()
            job_skill = (row.get("job_skill") or "").strip()
            if not syllabus_skill or not job_skill:
                raise EvaluationError(f"Row {row_number}: syllabus_skill and job_skill are required.")

            pairs.append(
                {
                    "syllabus_skill": syllabus_skill,
                    "job_skill": job_skill,
                    "true_label": parse_label(row.get("true_label"), row_number),
                    "row": row_number,
                }
            )

    if not pairs:
        raise EvaluationError(f"{csv_path.name} contains no data rows.")
    return pairs


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_pairs(pairs: list) -> list:
    """
    Attach the model's cosine similarity to each pair.

    compute_similarity_matrix() embeds two lists and returns every
    combination, so the diagonal is what we want: one call embeds the whole
    dataset at once rather than paying model overhead per row.
    """
    syllabus_skills = [p["syllabus_skill"] for p in pairs]
    job_skills = [p["job_skill"] for p in pairs]

    matrix = compute_similarity_matrix(syllabus_skills, job_skills).cpu().numpy()

    for index, pair in enumerate(pairs):
        pair["similarity"] = float(matrix[index][index])
    return pairs


def confusion(pairs: list, threshold: float) -> dict:
    """Classify every pair at `threshold` and count the four outcomes."""
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    for pair in pairs:
        predicted = pair["similarity"] >= threshold
        actual = pair["true_label"]
        if predicted and actual:
            counts["tp"] += 1
        elif predicted and not actual:
            counts["fp"] += 1
        elif not predicted and actual:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
    return counts


def metrics(counts: dict) -> dict:
    """
    Precision, recall, F1 and accuracy from a confusion matrix.

    Each guards its own zero denominator: with a small labelled set it is
    entirely possible for a threshold to predict no matches at all, and that
    should report as 0.0 rather than crash the run.
    """
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0.0

    return {"precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy, "total": total}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_confusion_matrix(counts: dict) -> None:
    tp, fp, tn, fn = counts["tp"], counts["fp"], counts["tn"], counts["fn"]

    # Wide enough for the longest column label ("no match") and for the
    # largest count, so the grid stays aligned on any dataset size.
    width = max(len("no match"), max(len(str(v)) for v in (tp, fp, tn, fn))) + 2
    label_col = 18  # left gutter holding the "actual" row labels

    print("  Confusion matrix")
    print()
    print(f"{' ' * (label_col + 1)}{'predicted':^{width * 2 + 1}}")
    print(f"{' ' * (label_col + 1)}{'match':^{width}} {'no match':^{width}}")
    print(f"{' ' * label_col}+{'-' * width}+{'-' * width}+")
    print(f"{'  actual  match':<{label_col}}|{tp:^{width}}|{fn:^{width}}|")
    print(f"{' ' * label_col}+{'-' * width}+{'-' * width}+")
    print(f"{'       no match':<{label_col}}|{fp:^{width}}|{tn:^{width}}|")
    print(f"{' ' * label_col}+{'-' * width}+{'-' * width}+")
    print()
    print(f"    true positives  {tp:>4}    false positives {fp:>4}")
    print(f"    false negatives {fn:>4}    true negatives  {tn:>4}")


def print_metrics(results: dict) -> None:
    print("  Metrics")
    print()
    print(f"    {'metric':<12} {'value':>8}")
    print(f"    {'-' * 12} {'-' * 8}")
    for name in ("precision", "recall", "f1", "accuracy"):
        print(f"    {name:<12} {results[name]:>8.3f}")
    print(f"    {'-' * 12} {'-' * 8}")
    print(f"    {'pairs':<12} {results['total']:>8}")


def print_pair_table(pairs: list, threshold: float) -> None:
    print("  Per-pair results")
    print()
    header = f"    {'syllabus_skill':<26} {'job_skill':<22} {'sim':>6} {'true':>6} {'pred':>6}  outcome"
    print(header)
    print(f"    {'-' * 26} {'-' * 22} {'-' * 6} {'-' * 6} {'-' * 6}  {'-' * 7}")

    for pair in pairs:
        predicted = pair["similarity"] >= threshold
        actual = pair["true_label"]
        outcome = (
            "TP" if predicted and actual
            else "FP" if predicted
            else "FN" if actual
            else "TN"
        )
        flag = "" if outcome in ("TP", "TN") else "   <-- wrong"
        print(
            f"    {pair['syllabus_skill'][:25]:<26} {pair['job_skill'][:21]:<22} "
            f"{pair['similarity']:>6.3f} {str(actual):>6} {str(predicted):>6}  {outcome}{flag}"
        )


def print_sweep(pairs: list, thresholds=SWEEP_THRESHOLDS) -> None:
    """
    Score the same dataset at several thresholds.

    The threshold is the one free parameter in the matcher, and the only
    honest way to choose it is to see what it costs at each setting.
    """
    print("  Threshold sweep")
    print()
    print(f"    {'thresh':>7} {'precision':>10} {'recall':>8} {'f1':>8} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}")
    print(f"    {'-' * 7} {'-' * 10} {'-' * 8} {'-' * 8} {'-' * 4} {'-' * 4} {'-' * 4} {'-' * 4}")

    best_f1, best_threshold = -1.0, None
    for threshold in thresholds:
        counts = confusion(pairs, threshold)
        results = metrics(counts)
        if results["f1"] > best_f1:
            best_f1, best_threshold = results["f1"], threshold
        print(
            f"    {threshold:>7.2f} {results['precision']:>10.3f} {results['recall']:>8.3f} "
            f"{results['f1']:>8.3f} {counts['tp']:>4} {counts['fp']:>4} "
            f"{counts['fn']:>4} {counts['tn']:>4}"
        )

    print()
    print(f"    Best F1 at threshold {best_threshold:.2f} (F1 = {best_f1:.3f})")


def print_errors(pairs: list, threshold: float) -> None:
    wrong = [p for p in pairs if (p["similarity"] >= threshold) != p["true_label"]]
    if not wrong:
        print("  No misclassified pairs at this threshold.")
        return

    print(f"  Misclassified pairs ({len(wrong)})")
    print()
    for pair in wrong:
        predicted = pair["similarity"] >= threshold
        kind = "false positive" if predicted else "false negative"
        print(f"    row {pair['row']:>3}  [{kind}]  sim={pair['similarity']:.3f}")
        print(f"             {pair['syllabus_skill']!r}")
        print(f"          vs {pair['job_skill']!r}")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the matching engine against a labelled dataset."
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help=f"Labelled CSV with columns {', '.join(REQUIRED_COLUMNS)} (default: {DEFAULT_CSV.name})",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_SIMILARITY_THRESHOLD,
        help=f"Similarity cut for a predicted match (default: {DEFAULT_SIMILARITY_THRESHOLD}).",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Also score the dataset across a range of thresholds.",
    )
    parser.add_argument(
        "--show-errors",
        action="store_true",
        help="List every misclassified pair with its similarity.",
    )
    parser.add_argument(
        "--no-pairs",
        action="store_true",
        help="Skip the per-pair table (useful on a large dataset).",
    )
    args = parser.parse_args()

    try:
        pairs = load_pairs(args.csv)
    except EvaluationError as exc:
        sys.exit(f"\nERROR: {exc}")

    positives = sum(1 for p in pairs if p["true_label"])
    print("=" * 76)
    print("MATCHING ENGINE EVALUATION")
    print("=" * 76)
    print(f"\n  dataset    {args.csv}")
    print(f"  pairs      {len(pairs)}  ({positives} labelled match, {len(pairs) - positives} labelled no-match)")
    print(f"  threshold  {args.threshold}")
    print("\n  Loading the model and embedding all pairs...")

    try:
        score_pairs(pairs)
    except (ValueError, RuntimeError) as exc:
        sys.exit(f"\nERROR: matching engine failed: {exc}")

    print()
    if not args.no_pairs:
        print("-" * 76)
        print_pair_table(pairs, args.threshold)
        print()

    counts = confusion(pairs, args.threshold)
    results = metrics(counts)

    print("-" * 76)
    print_confusion_matrix(counts)
    print()
    print("-" * 76)
    print_metrics(results)

    if args.sweep:
        print()
        print("-" * 76)
        print_sweep(pairs)

    if args.show_errors:
        print()
        print("-" * 76)
        print_errors(pairs, args.threshold)

    print()
    print("=" * 76)


if __name__ == "__main__":
    main()
