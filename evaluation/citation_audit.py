"""Citation precision over stored benchmark answers.

Box 15 asks for hallucination reported as the share of claims with no support,
not as a 1 to 5 rating. The judge produces a rating; this produces the share.

Answers from a completed run are re-checked with the citation validator against
the context that answer actually saw, read from the exported contexts for the
run. Rebuilding the context instead would re-retrieve from whatever the corpus
holds today, so any later correction to a source document would silently change
the reported figures for a run that never used it. The export is the record of
what was retrieved at the time. Rebuilding remains as a fallback for runs with
no export, and costs embedding calls only, no completions.

Run with:  python -m evaluation.citation_audit [path_to_ablation_csv]
"""

import csv
import glob
import json
import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import citation_validator
from evaluation.ablation_eval import CONDITIONS, build_context
from evaluation.export_contexts import corpus_check
from knowledge.rag_pipeline import RAGPipeline


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


def stored_contexts(csv_path):
    """Map (question_id, condition) to the context recorded for that run.

    Only an export made from this run's CSV is used. Taking the newest export
    regardless meant auditing one run against another run's contexts, and
    rebuilding everything it lacked. Returns an empty map when there is none.
    """
    wanted = os.path.basename(csv_path)
    exports = sorted(glob.glob("evaluation/results/retrieved_contexts_*.jsonl"))
    matching = []
    for export_path in exports:
        meta_path = export_path.replace(".jsonl", "_manifest.json")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as f:
            if json.load(f).get("source_csv") == wanted:
                matching.append(export_path)
    if not matching:
        return {}

    contexts = {}
    for line in open(matching[-1], encoding="utf-8"):
        record = json.loads(line)
        contexts[(record["question_id"], record["condition"])] = record.get(
            "retrieved_context", ""
        )
    if contexts:
        print(f"Using recorded contexts from {os.path.basename(matching[-1])}")
    return contexts


def audit(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    rows = [r for r in rows if r.get("answer") and not r["answer"].startswith("ERROR")]
    recorded = stored_contexts(path)

    missing = {(r["question_id"], r["condition"]) for r in rows} - set(recorded)
    if missing:
        matches, stored_hash, current = corpus_check(path)
        if not matches:
            raise SystemExit(
                f"{len(missing)} context(s) for {os.path.basename(path)} are not in a "
                f"recorded export, and the corpus has changed since that run "
                f"(recorded {str(stored_hash)[:12]}, now {current[:12]}). Rebuilding "
                "them would audit answers against text the model never saw."
            )
    rag = None
    rebuilt = 0

    # Contexts are identical across conditions for a given question, so cache.
    cache = {}
    results = []

    for i, row in enumerate(rows, 1):
        condition = row["condition"]
        key = (row["question_id"], condition)
        if key in recorded:
            context = recorded[key]
        else:
            if key not in cache:
                if rag is None:
                    rag = RAGPipeline()
                cache[key] = build_context(
                    row["question"], row["standard"], condition, rag
                )
                rebuilt += 1
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
    path = sys.argv[1] if len(sys.argv) > 1 else default_csv()
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
