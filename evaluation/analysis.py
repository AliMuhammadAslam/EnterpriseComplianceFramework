"""Reproduce the reported results tables from a stored ablation run.

The ablation script writes per-question scores but does not compute the summary
tables, so the means and intervals in the write-up could not be regenerated from
the repository. This script closes that gap: it reads the per-question CSV and
prints the per-configuration table and the paired-difference table.

Method, stated here so it does not have to be inferred:

  Scores are the primary judge's mean over the three metrics for one question
  under one configuration. The second judge is used only for the agreement
  check reported by the ablation script, and is never averaged into these
  numbers, because the two judges differ by roughly half a point and mixing
  them would hide that.

  Each comparison is paired by question. For every question answered under both
  configurations, the difference is taken, and a 95% interval is formed as
  mean(d) +/- t * sd(d) / sqrt(n), with t from the Student distribution on n-1
  degrees of freedom. Pairing by question removes question difficulty from the
  comparison, which matters because the benchmark is deliberately uneven.

Run with:  python -m evaluation.analysis [path_to_ablation_csv]
"""

import csv
import glob
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

csv.field_size_limit(10_000_000)

# Two-sided 95% critical values. Falls back to the normal approximation for
# sample sizes not listed, which only happens on the smaller category subsets.
T_CRITICAL = {
    4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646, 8: 2.3060, 9: 2.2622,
    10: 2.2281, 11: 2.2010, 12: 2.1788, 13: 2.1604, 14: 2.1448, 15: 2.1314,
    16: 2.1199, 17: 2.1098, 18: 2.1009, 19: 2.0930, 20: 2.0860, 24: 2.0639,
    29: 2.0452, 33: 2.0345, 34: 2.0322, 39: 2.0227, 41: 2.0195,
}

COMPARISONS = [
    ("Retrieval against no retrieval", "fixed_rag", "no_retrieval", None),
    ("Standard-specific retrieval", "standard_specific_fixed", "fixed_rag", None),
    ("Standard-specific retrieval, multi-step questions",
     "standard_specific_fixed", "fixed_rag", "multi_step"),
    ("Section-aware chunking under per-standard retrieval",
     "standard_specific_section_aware", "standard_specific_fixed", None),
    ("Multi-step planner on fixed chunks",
     "ecf_tuned", "standard_specific_fixed", None),
]


# The run the thesis reports. Other runs must be named on the command line.
REPORTED_RUN = "ablation_20260903_014438"


def default_csv():
    """The development run, which is the one the reported tables come from.

    Picking the newest file instead would silently switch to the reserved-question
    run, whose seven questions do not reproduce the reported tables. Pass a path
    explicitly to audit any other run.
    """
    matches = sorted(glob.glob("evaluation/results/ablation_2026*.csv"))
    if not matches:
        print("No ablation results found. Run the ablation first.")
        sys.exit(1)
    preferred = [m for m in matches if REPORTED_RUN in m]
    chosen = preferred[0] if preferred else matches[0]
    others = [m for m in matches if m != chosen]
    if others:
        print("Using the reported development run. Other runs present: %s"
              % ", ".join(os.path.basename(o) for o in others))
    return chosen


def load(path):
    """Return per-question primary-judge means, and each question's category."""
    scores, category = {}, {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row.get("mean"):
                continue
            scores.setdefault(row["condition"], {})[row["question_id"]] = float(row["mean"])
            category[row["question_id"]] = row.get("category", "")
    return scores, category


def t_value(n):
    return T_CRITICAL.get(n - 1, 1.96)


def paired_difference(scores, category, a, b, only=None):
    """Mean paired difference a - b, with a 95% interval."""
    questions = [
        q for q in scores.get(a, {})
        if q in scores.get(b, {}) and (only is None or category.get(q) == only)
    ]
    diffs = [scores[a][q] - scores[b][q] for q in questions]
    if len(diffs) < 2:
        return len(diffs), (statistics.mean(diffs) if diffs else 0.0), None, None

    mean = statistics.mean(diffs)
    margin = t_value(len(diffs)) * statistics.stdev(diffs) / math.sqrt(len(diffs))
    return len(diffs), mean, mean - margin, mean + margin


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else default_csv()
    scores, category = load(path)
    print(f"Source: {os.path.basename(path)}\n")

    print("Performance by configuration (primary judge)")
    print(f"{'Configuration':36s} {'n':>4} {'Mean':>7} {'SD':>7}")
    ranked = sorted(scores, key=lambda c: -statistics.mean(list(scores[c].values())))
    for condition in ranked:
        values = list(scores[condition].values())
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        print(f"{condition:36s} {len(values):4d} {statistics.mean(values):7.2f} {sd:7.2f}")

    print("\nPaired differences with 95% intervals")
    print(f"{'Comparison':52s} {'n':>4} {'Diff':>8}  95% interval")
    for label, a, b, only in COMPARISONS:
        n, diff, low, high = paired_difference(scores, category, a, b, only)
        interval = f"[{low:+.3f}, {high:+.3f}]" if low is not None else "not computable"
        print(f"{label:52s} {n:4d} {diff:+8.3f}  {interval}")


if __name__ == "__main__":
    main()
