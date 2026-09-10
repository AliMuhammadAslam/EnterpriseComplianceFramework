"""Citation precision over stored benchmark answers.

Box 15 asks for hallucination reported as the share of claims with no support,
not as a 1 to 5 rating. The judge produces a rating; this produces the share.

Answers from a completed run are re-checked with the citation validator. The
context each answer saw is rebuilt rather than stored, which is safe because
retrieval is deterministic for a fixed corpus and query. Embedding calls only,
no completions.

Run with:  python -m evaluation.citation_audit [path_to_ablation_csv]
"""

import csv
import glob
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import citation_validator
from evaluation.ablation_eval import CONDITIONS, build_context
from knowledge.rag_pipeline import RAGPipeline


def latest_csv():
    matches = sorted(glob.glob("evaluation/results/ablation_2026*.csv"))
    if not matches:
        print("No ablation results found. Run the ablation first.")
        sys.exit(1)
    return matches[-1]


def audit(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    rows = [r for r in rows if r.get("answer") and not r["answer"].startswith("ERROR")]
    rag = RAGPipeline()

    # Contexts are identical across conditions for a given question, so cache.
    cache = {}
    results = []

    for i, row in enumerate(rows, 1):
        condition = row["condition"]
        key = (row["question_id"], condition)
        if key not in cache:
            cache[key] = build_context(
                row["question"], row["standard"], condition, rag
            )
        context = cache[key]

        report = citation_validator.validate(row["answer"], context)
        results.append({
            "question_id": row["question_id"],
            "category": row.get("category", "single_fact"),
            "condition": condition,
            "total": report.total,
            "supported": len(report.supported),
            "unsupported": len(report.unsupported),
            "precision": report.precision,
            "unsupported_texts": "; ".join(c.text for c in report.unsupported),
        })
        if i % 25 == 0:
            print(f"  {i}/{len(rows)} answers checked")

    return results


def summarise(results, conditions):
    summary = []
    for condition in conditions:
        subset = [r for r in results if r["condition"] == condition]
        if not subset:
            continue
        total = sum(r["total"] for r in subset)
        unsupported = sum(r["unsupported"] for r in subset)
        with_claims = [r for r in subset if r["total"] > 0]
        clean = sum(1 for r in with_claims if r["unsupported"] == 0)
        summary.append({
            "condition": condition,
            "answers": len(subset),
            "answers_with_identifiers": len(with_claims),
            "identifiers": total,
            "unsupported": unsupported,
            "unsupported_share": round(unsupported / total, 3) if total else None,
            "mean_precision": round(
                statistics.mean(r["precision"] for r in with_claims), 3
            ) if with_claims else None,
            "fully_grounded_answers": round(
                clean / len(with_claims), 3
            ) if with_claims else None,
        })
    return summary


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else latest_csv()
    print(f"Auditing {path}\n")

    results = audit(path)
    conditions = [c for c in CONDITIONS if any(r["condition"] == c for r in results)]
    summary = summarise(results, conditions)

    out = "evaluation/results/citation_audit.md"
    lines = [
        "# Citation grounding over benchmark answers",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Source**: {os.path.basename(path)}",
        f"**Answers checked**: {len(results)}",
        "",
        "Every regulatory identifier in each answer was checked against the "
        "context that answer actually saw. This reports grounding as a share of "
        "claims rather than as a rating, which is what an ordinal judge score "
        "cannot give.",
        "",
        "An identifier counts as supported if it appears in a retrieved chunk. "
        "This verifies provenance, not truth: an identifier taken from a "
        "poisoned or incorrect source still counts as supported. See the "
        "fabricated regulation test for why that distinction matters.",
        "",
        "| Condition | Answers | Identifiers | Unsupported | Unsupported share | Fully grounded answers |",
        "|---|---|---|---|---|---|",
    ]
    for s in summary:
        lines.append(
            f"| {s['condition']} | {s['answers']} | {s['identifiers']} | "
            f"{s['unsupported']} | "
            f"{s['unsupported_share']:.1%} | "
            f"{s['fully_grounded_answers']:.0%} |"
            if s["unsupported_share"] is not None else
            f"| {s['condition']} | {s['answers']} | 0 | 0 | n/a | n/a |"
        )

    lines += ["", "## By question category", "",
              "| Condition | Category | Identifiers | Unsupported share |",
              "|---|---|---|---|"]
    for condition in conditions:
        for category in sorted({r["category"] for r in results}):
            subset = [r for r in results
                      if r["condition"] == condition and r["category"] == category]
            total = sum(r["total"] for r in subset)
            unsupported = sum(r["unsupported"] for r in subset)
            if total:
                lines.append(
                    f"| {condition} | {category} | {total} | "
                    f"{unsupported / total:.1%} |"
                )

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print()
    print(f"{'condition':<26}{'ids':>6}{'unsupported':>13}{'share':>9}")
    print("-" * 54)
    for s in summary:
        share = f"{s['unsupported_share']:.1%}" if s["unsupported_share"] is not None else "n/a"
        print(f"{s['condition']:<26}{s['identifiers']:>6}{s['unsupported']:>13}{share:>9}")
    print(f"\nWritten to {out}")


if __name__ == "__main__":
    main()
