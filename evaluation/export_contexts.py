"""Export the retrieved context behind every stored benchmark answer.

The ablation CSV records each answer but not the reference material the model
saw. Retrieval is deterministic for a fixed corpus and query, so the contexts
are rebuilt here and written out alongside the answers, giving a reviewer the
full input and output of each run without needing to regenerate anything.

Embedding calls only, no completions.

Run with:  python -m evaluation.export_contexts [path_to_ablation_csv]
"""

import csv
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.ablation_eval import build_context
from knowledge.rag_pipeline import RAGPipeline
from utils import run_config

csv.field_size_limit(10_000_000)


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


def export(path):
    with open(path, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("answer")]

    rag = RAGPipeline()
    cache = {}
    records = []

    for i, row in enumerate(rows, 1):
        key = (row["question_id"], row["condition"])
        if key not in cache:
            cache[key] = build_context(
                row["question"], row["standard"], row["condition"], rag
            )
        context = cache[key]

        records.append({
            "question_id": row["question_id"],
            "condition": row["condition"],
            "category": row.get("category", ""),
            "standard": row.get("standard", ""),
            "question": row["question"],
            "retrieved_context": context,
            "context_chars": len(context),
            "answer": row["answer"],
        })

        if i % 25 == 0:
            print(f"  {i}/{len(rows)} rows")

    return records


def write(records, source_csv):
    os.makedirs("evaluation/results", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"evaluation/results/retrieved_contexts_{stamp}.jsonl"

    with open(out, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    meta = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source_csv": os.path.basename(source_csv),
        "rows": len(records),
        "unique_contexts": len({(r["question_id"], r["condition"]) for r in records}),
        "embedding_model": run_config.embedding_model(),
        "git_commit": run_config.run_manifest().get("git_commit"),
    }
    with open(out.replace(".jsonl", "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote {len(records)} records to {out}")
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else default_csv()
    print(f"Rebuilding retrieved contexts for {os.path.basename(path)} ...")
    records = export(path)
    write(records, path)


if __name__ == "__main__":
    main()
