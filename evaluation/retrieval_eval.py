"""Retrieval quality measured on its own, without the language model.

The ablation scores whole answers, so a retrieval failure and a generation
failure look the same. This measures the retrieval step directly: does the
right source document come back, and where in the ranking does it land.

Relevance labels are source-level, not chunk-level. A retrieved chunk counts
as relevant if it came from the corpus file for the standard the question is
about. That is coarser than judging individual chunks, but it needs no manual
annotation and it is honest about what it measures. It cannot tell whether the
specific passage answering the question was retrieved, only whether the right
document was.

Costs embedding calls only, no completions.

Run with:  python -m evaluation.retrieval_eval
"""

import os
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.ablation_eval import FIXED_COLLECTION
from evaluation.benchmark_v2 import all_questions
from knowledge.vector_store import VectorStore, KNOWLEDGE_COLLECTION

# Standard names as they appear in the benchmark, mapped to their corpus file.
STANDARD_TO_SOURCE = {
    "SBP EMI Regulations 2019": "sbp_regulations.md",
    "SBP Branchless Banking Regulations": "sbp_regulations.md",
    "SBP Data Localisation Requirements": "sbp_regulations.md",
    "SBP Regulations": "sbp_regulations.md",
    "PECA 2016": "peca_2016.md",
    "Pakistan AML/CFT": "pakistan_aml_cft.md",
    "ISO 27001": "iso_27001.md",
    "ISO 22301": "iso_22301.md",
    "GDPR": "gdpr.md",
    "PCI DSS": "pci_dss.md",
}

K_VALUES = [1, 3, 5, 10]
MAX_K = max(K_VALUES)


def expected_sources(question):
    """Corpus files that should be retrieved for this question."""
    names = [s.strip() for s in question["standard"].split(",") if s.strip()]
    sources = set()
    for name in names:
        source = STANDARD_TO_SOURCE.get(name)
        if source:
            sources.add(source)
    return sources


def retrieved_sources(store, query, collection, top_k):
    """Source filenames of the top_k chunks, in rank order."""
    results = store.query_knowledge(query, top_k=top_k, collection_name=collection)
    return [r["metadata"].get("source", "") for r in results]


def evaluate_combined(store, questions, collection):
    """One query per question, the production path for a general query."""
    rows = []
    for q in questions:
        wanted = expected_sources(q)
        if not wanted:
            continue
        ranked = retrieved_sources(store, q["question"], collection, MAX_K)
        rows.append(_score(q, wanted, ranked))
    return rows


def evaluate_per_standard(store, questions, collection, per_standard_k=5):
    """One query per named standard, interleaved, mirroring the ECF path."""
    rows = []
    for q in questions:
        wanted = expected_sources(q)
        if not wanted:
            continue
        names = [s.strip() for s in q["standard"].split(",") if s.strip()]
        ranked = []
        per_standard = []
        for name in names:
            query = f"{name} requirements controls compliance obligations {q['question']}"
            per_standard.append(
                retrieved_sources(store, query, collection, per_standard_k)
            )
        # Interleave so rank reflects the order a reader would encounter them.
        for i in range(per_standard_k):
            for block in per_standard:
                if i < len(block):
                    ranked.append(block[i])
        rows.append(_score(q, wanted, ranked))
    return rows


def _score(question, wanted, ranked):
    """Recall at each k, reciprocal rank, and full coverage for multi-standard."""
    row = {
        "id": question["id"],
        "category": question.get("category", "single_fact"),
        "wanted": sorted(wanted),
        "n_wanted": len(wanted),
    }

    for k in K_VALUES:
        top = ranked[:k]
        row[f"hit@{k}"] = int(any(s in wanted for s in top))
        row[f"coverage@{k}"] = len(wanted & set(top)) / len(wanted)
        row[f"all@{k}"] = int(wanted.issubset(set(top)))

    rank = next((i + 1 for i, s in enumerate(ranked) if s in wanted), 0)
    row["first_relevant_rank"] = rank
    row["reciprocal_rank"] = 1.0 / rank if rank else 0.0
    return row


def summarise(rows, label):
    if not rows:
        return None
    entry = {"strategy": label, "n": len(rows)}
    for k in K_VALUES:
        entry[f"recall@{k}"] = round(statistics.mean(r[f"hit@{k}"] for r in rows), 3)
        entry[f"coverage@{k}"] = round(statistics.mean(r[f"coverage@{k}"] for r in rows), 3)
        entry[f"all@{k}"] = round(statistics.mean(r[f"all@{k}"] for r in rows), 3)
    entry["mrr"] = round(statistics.mean(r["reciprocal_rank"] for r in rows), 3)
    found = [r["first_relevant_rank"] for r in rows if r["first_relevant_rank"]]
    entry["median_rank_of_first_hit"] = statistics.median(found) if found else None
    entry["never_retrieved"] = sum(1 for r in rows if not r["first_relevant_rank"])
    return entry


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main():
    store = VectorStore()
    questions = all_questions(include_holdout=True)
    questions = [q for q in questions if expected_sources(q)]

    configs = [
        ("section-aware, single query", KNOWLEDGE_COLLECTION, "combined"),
        ("fixed-size, single query", FIXED_COLLECTION, "combined"),
        ("section-aware, per standard", KNOWLEDGE_COLLECTION, "per_standard"),
        ("fixed-size, per standard", FIXED_COLLECTION, "per_standard"),
    ]

    summaries, detail = [], {}
    for label, collection, mode in configs:
        print(f"Measuring: {label} ...", end=" ", flush=True)
        if mode == "combined":
            rows = evaluate_combined(store, questions, collection)
        else:
            rows = evaluate_per_standard(store, questions, collection)
        detail[label] = rows
        summary = summarise(rows, label)
        summaries.append(summary)
        print(f"recall@5 {summary['recall@5']:.2f}  MRR {summary['mrr']:.2f}")

    _write_report(summaries, detail, questions)


def _write_report(summaries, detail, questions):
    os.makedirs("evaluation/results", exist_ok=True)
    path = "evaluation/results/retrieval_metrics.md"

    lines = [
        "# Retrieval quality",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Questions**: {len(questions)} (holdout included, no model calls involved)",
        "",
        "Relevance is judged at source-document level: a retrieved chunk counts "
        "as relevant if it came from the corpus file for the standard the "
        "question asks about. This needs no manual annotation, but it measures "
        "only whether the right document was found, not whether the specific "
        "passage that answers the question was among the chunks.",
        "",
        "recall@k is the share of questions with at least one relevant chunk in "
        "the top k. coverage@k is the share of the required sources retrieved, "
        "which matters for questions spanning several standards. all@k is the "
        "share of questions where every required source appeared.",
        "",
        _table(
            ["Strategy", "n", "recall@1", "recall@5", "coverage@5", "all@5", "MRR", "Never found"],
            [[s["strategy"], s["n"], f"{s['recall@1']:.2f}", f"{s['recall@5']:.2f}",
              f"{s['coverage@5']:.2f}", f"{s['all@5']:.2f}", f"{s['mrr']:.2f}",
              s["never_retrieved"]] for s in summaries],
        ),
        "",
        "## Multi-standard questions only",
        "",
        "The case standard-specific retrieval exists for.",
        "",
    ]

    multi_rows = []
    for label, rows in detail.items():
        subset = [r for r in rows if r["n_wanted"] > 1]
        s = summarise(subset, label)
        if s:
            multi_rows.append([
                label, s["n"], f"{s['recall@5']:.2f}", f"{s['coverage@5']:.2f}",
                f"{s['all@5']:.2f}", f"{s['mrr']:.2f}",
            ])
    lines.append(_table(
        ["Strategy", "n", "recall@5", "coverage@5", "all@5", "MRR"], multi_rows,
    ))

    lines += ["", "## By category", ""]
    cat_rows = []
    for label, rows in detail.items():
        for category in sorted({r["category"] for r in rows}):
            subset = [r for r in rows if r["category"] == category]
            s = summarise(subset, label)
            cat_rows.append([label, category, s["n"], f"{s['recall@5']:.2f}",
                             f"{s['coverage@5']:.2f}", f"{s['mrr']:.2f}"])
    lines.append(_table(
        ["Strategy", "Category", "n", "recall@5", "coverage@5", "MRR"], cat_rows,
    ))
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nWritten to {path}")


if __name__ == "__main__":
    main()
