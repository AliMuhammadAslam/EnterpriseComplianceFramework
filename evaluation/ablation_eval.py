"""Component ablation benchmark for the ECF retrieval design.

The original benchmark compared a bare GPT-4o call against the complete
framework, which cannot show which component produced the difference. This
runner isolates them by holding the model, prompts, corpus and generation
budget constant and varying one component at a time:

  no_retrieval            no context at all (parametric memory only)
  fixed_rag               fixed-size chunking, one combined query
  section_aware_only      section-aware chunking, one combined query
  standard_specific_only  fixed-size chunking, one query per standard
  full_ecf_no_planner     section-aware chunking, one query per standard
  full_ecf                as above, plus the multi-step planner and executor

Comparing full_ecf against full_ecf_no_planner isolates the agent pipeline.
Comparing section_aware_only against fixed_rag isolates the chunker. Comparing
standard_specific_only against fixed_rag isolates per-standard retrieval.

Both chunking strategies must be indexed before running. Use --ingest once.

Usage:
    python -m evaluation.ablation_eval --ingest
    python -m evaluation.ablation_eval
    python -m evaluation.ablation_eval --conditions fixed_rag,full_ecf
    python -m evaluation.ablation_eval --judge-model gpt-4o-2024-08-06
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from litellm import completion

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.quantitative_eval import QUESTIONS, JUDGE_PROMPT
from knowledge import knowledge_base as kb
from knowledge.rag_pipeline import RAGPipeline
from knowledge.vector_store import VectorStore, KNOWLEDGE_COLLECTION
from utils import run_config

# Second collection holding the same corpus under fixed-size chunking.
FIXED_COLLECTION = "regulatory_knowledge_fixed"

ANSWER_MAX_TOKENS = 600

# Held constant across every condition so the only variable is the component
# under test. Baseline gets no reference material; the rest share this wording.
BASELINE_SYSTEM = (
    "You are a compliance and regulatory expert. Answer the question "
    "accurately. Cite specific clause numbers, article numbers, section "
    "references, and exact numerical values where applicable."
)
GROUNDED_SYSTEM = (
    "You are a compliance expert. Use ONLY the provided reference "
    "material to answer. Cite specific identifiers and values exactly "
    "as they appear in the reference material.\n\n"
    "REFERENCE MATERIAL:\n{context}"
)

DEFAULT_TOP_K = 5

# Every condition is held to the same context budget, about 14,000 characters,
# so a difference in score cannot be a difference in how much text the model
# was given. The k values below were measured across the benchmark, not
# guessed: section-aware chunks average 91 words against 364 for fixed-size,
# and per-standard retrieval issues one query per standard, so equal k would
# have meant wildly unequal context.
#
#   fixed, combined            k=5   14359 chars
#   section-aware, combined    k=16  ~13970
#   fixed, per standard        k=3   15354
#   section-aware, per standard k=10 14518
CONTEXT_BUDGET_CHARS = 14359

# retrieval: none | combined | per_standard
CONDITIONS = {
    "no_retrieval": {
        "retrieval": "none", "collection": None, "planner": False},
    "fixed_rag": {
        "retrieval": "combined", "collection": FIXED_COLLECTION,
        "planner": False, "top_k": 5},
    "section_aware_rag": {
        "retrieval": "combined", "collection": KNOWLEDGE_COLLECTION,
        "planner": False, "top_k": 16},
    "standard_specific_fixed": {
        "retrieval": "per_standard", "collection": FIXED_COLLECTION,
        "planner": False, "top_k": 3},
    "standard_specific_section_aware": {
        "retrieval": "per_standard", "collection": KNOWLEDGE_COLLECTION,
        "planner": False, "top_k": 10},
    # The architecture as originally designed: section-aware chunking,
    # per-standard retrieval, planner.
    "ecf_original": {
        "retrieval": "per_standard", "collection": KNOWLEDGE_COLLECTION,
        "planner": True, "top_k": 10},
    # The same architecture with the chunker swapped for fixed-size, which the
    # retrieval metrics showed gives better multi-document coverage.
    "ecf_tuned": {
        "retrieval": "per_standard", "collection": FIXED_COLLECTION,
        "planner": True, "top_k": 3},
}

METRICS = ["citation_accuracy", "hallucination_rate", "answer_relevance"]

_OBSERVED_FINGERPRINTS = set()


def _track(response):
    fingerprint = run_config.system_fingerprint(response)
    if fingerprint:
        _OBSERVED_FINGERPRINTS.add(fingerprint)
    return response


def ingest_both_collections():
    """Index the corpus twice, once per chunking strategy.

    Runs before any ablation so both collections exist and the comparison is
    not contaminated by re-indexing partway through.
    """
    store = VectorStore()
    for strategy, collection in (
        (kb.SECTION_AWARE, KNOWLEDGE_COLLECTION),
        (kb.FIXED_SIZE, FIXED_COLLECTION),
    ):
        print(f"Ingesting {strategy} into {collection} ...")
        base = kb.KnowledgeBase(store, chunk_strategy=strategy, collection_name=collection)
        base.ingest(force=True)
        print(f"  {store.knowledge_count(collection)} chunks")


def build_context(question, standard, condition, rag):
    """Assemble the reference material for one condition."""
    settings = CONDITIONS[condition]
    if settings["retrieval"] == "none":
        return ""

    top_k = settings.get("top_k", DEFAULT_TOP_K)

    if settings["retrieval"] == "combined":
        return rag.retrieve_knowledge_only(
            question, collection_name=settings["collection"], top_k=top_k
        )

    # Per-standard retrieval: one query per standard, combined into labelled
    # blocks, mirroring what the evaluation engine does in production.
    blocks = []
    for name in [s.strip() for s in standard.split(",") if s.strip()]:
        query = f"{name} requirements controls compliance obligations {question}"
        chunk = rag.retrieve_knowledge_only(
            query, collection_name=settings["collection"], top_k=top_k
        )
        blocks.append(f"=== {name} ===\n{chunk}")
    return "\n\n".join(blocks)


def answer_question(question, context, condition):
    """Produce an answer for one question under one condition."""
    if CONDITIONS[condition]["planner"]:
        return _answer_with_planner(question, context)

    system = BASELINE_SYSTEM if not context else GROUNDED_SYSTEM.format(context=context)
    response = _track(completion(
        model=run_config.litellm_model(),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        temperature=run_config.temperature(),
        max_tokens=ANSWER_MAX_TOKENS,
        seed=run_config.seed(),
    ))
    return response.choices[0].message.content.strip()


def _answer_with_planner(question, context):
    """Run the multi-step planner and executor over the same retrieved context.

    Isolates the agent pipeline: identical model, prompts and context as
    full_ecf_no_planner, differing only in decomposition and sequential
    execution.
    """
    from agent.planner import Planner
    from agent.executor import Executor
    from agent.perception import PerceptionOutput

    perception = PerceptionOutput(
        structured_input={"original_content": question, "source": "benchmark"},
        intent="information_seeking",
    )
    plan = Planner().create_plan(perception, rag_context=context)
    result = Executor().execute_plan(plan, rag_context=context)
    return result.result.strip()


def judge_answer(question, ground_truth, answer, judge_model):
    """Score one answer. Kept separate from generation so the judge can be varied."""
    prompt = JUDGE_PROMPT.format(
        question=question, ground_truth=ground_truth, answer=answer
    )
    response = _track(completion(
        model=judge_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=run_config.temperature(),
        max_tokens=80,
        seed=run_config.seed(),
    ))
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw.strip())


def run(conditions, judge_model, results_dir="evaluation/results",
        questions=None, second_judge=""):
    """Run every question under every condition and record per-question results.

    The judge receives only the question, the reference answer and the answer
    text. It is never told which condition produced what, so scoring is blind
    by construction rather than by discipline.
    """
    questions = questions if questions is not None else QUESTIONS
    rag = RAGPipeline()
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows = []
    total = len(questions) * len(conditions)
    step = 0

    for question in questions:
        for condition in conditions:
            step += 1
            print(f"[{step}/{total}] {question['id']:<12} {condition}", end=" ... ", flush=True)
            row = {
                "question_id": question["id"],
                "standard": question["standard"],
                "category": question.get("category", "single_fact"),
                "condition": condition,
                "question": question["question"],
            }
            try:
                context = build_context(
                    question["question"], question["standard"], condition, rag
                )
                answer = answer_question(question["question"], context, condition)
                scores = judge_answer(
                    question["question"], question["ground_truth"], answer, judge_model
                )

                for metric in METRICS:
                    row[metric] = scores[metric]
                row["mean"] = round(sum(scores[m] for m in METRICS) / len(METRICS), 4)
                row["context_chars"] = len(context)
                row["answer"] = answer

                if second_judge:
                    second = judge_answer(
                        question["question"], question["ground_truth"],
                        answer, second_judge,
                    )
                    for metric in METRICS:
                        row[f"j2_{metric}"] = second[metric]
                    row["j2_mean"] = round(
                        sum(second[m] for m in METRICS) / len(METRICS), 4
                    )
                    print(f"mean={row['mean']} j2={row['j2_mean']}")
                else:
                    print(f"mean={row['mean']}")

            except Exception as e:
                for metric in METRICS:
                    row[metric] = None
                    if second_judge:
                        row[f"j2_{metric}"] = None
                row["mean"] = None
                if second_judge:
                    row["j2_mean"] = None
                row["context_chars"] = None
                row["answer"] = f"ERROR: {e}"
                print(f"ERROR - {e}")

            rows.append(row)
            time.sleep(1)

    csv_path = f"{results_dir}/ablation_{timestamp}.csv"
    _write_csv(rows, csv_path)

    summary = summarise(rows, conditions)
    md_path = f"{results_dir}/ablation_{timestamp}.md"
    _write_markdown(summary, rows, md_path, judge_model,
                    conditions=conditions, second_judge=second_judge)

    manifest = run_config.run_manifest()
    manifest["observed_system_fingerprints"] = sorted(_OBSERVED_FINGERPRINTS)
    manifest["judge_model"] = judge_model
    manifest["conditions"] = {c: CONDITIONS[c] for c in conditions}
    manifest["questions"] = len(questions)
    manifest["question_ids"] = [q["id"] for q in questions]
    manifest["answer_max_tokens"] = ANSWER_MAX_TOKENS
    manifest["second_judge"] = second_judge
    manifest["judge_blind"] = (
        "The judge receives only question, reference answer and answer text. "
        "Condition labels are never passed to it."
    )
    agreement = judge_agreement(rows)
    if agreement:
        manifest["judge_agreement"] = agreement
    manifest_path = f"{results_dir}/ablation_manifest_{timestamp}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nSaved:\n  {csv_path}\n  {md_path}\n  {manifest_path}\n")
    _print_summary(summary)
    return rows


def judge_agreement(rows):
    """How often the two judges gave the same score.

    Reported per metric on the raw 1-5 ratings. Exact agreement is strict for
    an ordinal scale, so agreement within one point is reported alongside it.
    """
    paired = [r for r in rows if r.get("j2_mean") is not None and r.get("mean") is not None]
    if not paired:
        return None

    report = {"n": len(paired)}
    for metric in METRICS:
        a = [r[metric] for r in paired if r.get(metric) is not None]
        b = [r[f"j2_{metric}"] for r in paired if r.get(f"j2_{metric}") is not None]
        if len(a) != len(b) or not a:
            continue
        exact = sum(1 for x, y in zip(a, b) if x == y) / len(a)
        within1 = sum(1 for x, y in zip(a, b) if abs(x - y) <= 1) / len(a)
        report[metric] = {
            "exact": round(exact, 3),
            "within_one": round(within1, 3),
            "judge1_mean": round(statistics.mean(a), 3),
            "judge2_mean": round(statistics.mean(b), 3),
        }

    m1 = [r["mean"] for r in paired]
    m2 = [r["j2_mean"] for r in paired]
    report["overall"] = {
        "judge1_mean": round(statistics.mean(m1), 3),
        "judge2_mean": round(statistics.mean(m2), 3),
        "mean_absolute_difference": round(
            statistics.mean(abs(x - y) for x, y in zip(m1, m2)), 3
        ),
    }
    if len(m1) > 1 and statistics.stdev(m1) > 0 and statistics.stdev(m2) > 0:
        report["overall"]["correlation"] = round(_pearson(m1, m2), 3)
    return report


def _pearson(xs, ys):
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den if den else 0.0


def summarise_by_category(rows, conditions):
    """Mean score per condition split by question category.

    The v1 benchmark could not separate components partly because every
    question was a single-standard lookup. Splitting by category shows whether
    a component only earns its place on the harder ones.
    """
    categories = sorted({r.get("category", "single_fact") for r in rows})
    table = {}
    for condition in conditions:
        entry = {}
        for category in categories:
            values = [
                r["mean"] for r in rows
                if r["condition"] == condition
                and r.get("category", "single_fact") == category
                and r["mean"] is not None
            ]
            entry[category] = round(statistics.mean(values), 3) if values else None
        table[condition] = entry
    return table, categories


def summarise(rows, conditions):
    """Mean and standard deviation per metric per condition, plus n."""
    summary = {}
    for condition in conditions:
        subset = [r for r in rows if r["condition"] == condition and r["mean"] is not None]
        entry = {"n": len(subset)}

        # Recorded so any remaining difference in how much text a condition saw
        # is visible next to its scores rather than left implicit.
        chars = [r["context_chars"] for r in subset if r.get("context_chars") is not None]
        entry["context_chars_mean"] = round(statistics.mean(chars)) if chars else None

        for metric in METRICS + ["mean"]:
            values = [r[metric] for r in subset if r.get(metric) is not None]
            entry[metric] = {
                "mean": round(statistics.mean(values), 3) if values else None,
                "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else None,
            }
        summary[condition] = entry
    return summary


def _write_csv(rows, path):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(summary, rows, path, judge_model, conditions=None, second_judge=""):
    question_count = len({r["question_id"] for r in rows})
    lines = [
        "# Component Ablation Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Model**: {run_config.model_name()} (seed {run_config.seed()}, "
        f"temperature {run_config.temperature()})",
        f"**Judge**: {judge_model}",
    ]
    if second_judge:
        lines.append(f"**Second judge**: {second_judge}")
    lines += [
        f"**Questions**: {question_count}",
        "",
        "Scoring is blind: the judge is given the question, the reference "
        "answer and the answer text, never the condition that produced it.",
        "",
        "Scores are 1 to 5, higher is better. Absolute differences are reported "
        "rather than percentage changes, because these are ordinal ratings "
        "without a meaningful zero.",
        "",
        "Context size is shown because section-aware chunks are smaller than "
        "fixed ones, so equal top_k does not mean equal context. The "
        "section_aware_matched condition uses a larger top_k chosen to match "
        "fixed_rag on retrieved words, which separates the chunking strategy "
        "from the amount of text supplied.",
        "",
        "| Condition | n | Context chars | Citation | No-hallucination | Relevance | Overall (SD) |",
        "|---|---|---|---|---|---|---|",
    ]

    def cell(entry, metric):
        value = entry[metric]["mean"]
        return f"{value:.2f}" if value is not None else "n/a"

    for condition, entry in summary.items():
        overall = entry["mean"]["mean"]
        stdev = entry["mean"]["stdev"]
        overall_cell = (
            f"{overall:.2f}" + (f" ({stdev:.2f})" if stdev is not None else "")
            if overall is not None else "n/a"
        )
        context = entry.get("context_chars_mean")
        lines.append(
            f"| {condition} | {entry['n']} | {context if context is not None else 'n/a'} | "
            f"{cell(entry, 'citation_accuracy')} | "
            f"{cell(entry, 'hallucination_rate')} | {cell(entry, 'answer_relevance')} | "
            f"{overall_cell} |"
        )

    if conditions:
        table, categories = summarise_by_category(rows, conditions)
        lines += [
            "",
            "## Scores by question category",
            "",
            "A component that only pays off on harder questions will show it "
            "here rather than in the overall mean.",
            "",
            "| Condition | " + " | ".join(categories) + " |",
            "|" + "|".join("---" for _ in range(len(categories) + 1)) + "|",
        ]
        for condition in conditions:
            cells = [
                f"{table[condition][c]:.2f}" if table[condition].get(c) is not None else "n/a"
                for c in categories
            ]
            lines.append(f"| {condition} | " + " | ".join(cells) + " |")

    agreement = judge_agreement(rows)
    if agreement:
        lines += [
            "",
            "## Judge agreement",
            "",
            f"Two independent judges scored every answer (n = {agreement['n']} "
            "answer-judge pairs). Exact agreement is strict on a 1 to 5 ordinal "
            "scale, so agreement within one point is given alongside it.",
            "",
            "| Metric | Exact | Within 1 | Judge 1 mean | Judge 2 mean |",
            "|---|---|---|---|---|",
        ]
        for metric in METRICS:
            if metric in agreement:
                a = agreement[metric]
                lines.append(
                    f"| {metric} | {a['exact']:.0%} | {a['within_one']:.0%} | "
                    f"{a['judge1_mean']:.2f} | {a['judge2_mean']:.2f} |"
                )
        overall = agreement["overall"]
        lines += [
            "",
            f"Overall means: judge 1 {overall['judge1_mean']:.2f}, judge 2 "
            f"{overall['judge2_mean']:.2f}. Mean absolute difference "
            f"{overall['mean_absolute_difference']:.2f}."
            + (f" Correlation {overall['correlation']:.2f}."
               if "correlation" in overall else ""),
        ]

    lines += ["", "## Per-question scores", "",
              "| Question | Standard | Condition | Citation | No-hallucination | Relevance | Mean |",
              "|---|---|---|---|---|---|---|"]
    for row in rows:
        values = [row.get(m) for m in METRICS] + [row.get("mean")]
        rendered = " | ".join("n/a" if v is None else str(v) for v in values)
        lines.append(
            f"| {row['question_id']} | {row['standard']} | {row['condition']} | {rendered} |"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _print_summary(summary):
    print(f"{'condition':<24} {'n':>3} {'overall':>8} {'sd':>7}")
    print("-" * 46)
    for condition, entry in summary.items():
        overall = entry["mean"]["mean"]
        stdev = entry["mean"]["stdev"]
        print(
            f"{condition:<24} {entry['n']:>3} "
            f"{overall if overall is not None else 'n/a':>8} "
            f"{stdev if stdev is not None else '-':>7}"
        )


def main():
    parser = argparse.ArgumentParser(description="Run the ECF component ablation benchmark.")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Index the corpus under both chunking strategies, then exit.",
    )
    parser.add_argument(
        "--conditions",
        type=str,
        default=",".join(CONDITIONS),
        help="Comma-separated subset of conditions to run.",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="",
        help="Judge model. Defaults to the pinned snapshot. Set a different "
             "model to measure agreement between judges.",
    )
    parser.add_argument(
        "--second-judge",
        type=str,
        default="",
        help="A second judge model. When set, every answer is scored twice and "
             "agreement between the two judges is reported.",
    )
    parser.add_argument(
        "--question-set",
        type=str,
        choices=["v1", "v2"],
        default="v1",
        help="v1 is the original 10 questions. v2 is the 30-question set with "
             "multi-standard and multi-step categories, holdout excluded.",
    )
    parser.add_argument(
        "--include-holdout",
        action="store_true",
        help="Include the reserved holdout questions. Only for a final run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Run only the first N questions. For smoke testing, not results.",
    )
    args = parser.parse_args()

    if args.ingest:
        ingest_both_collections()
        return

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = [c for c in conditions if c not in CONDITIONS]
    if unknown:
        print(f"Unknown condition(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(CONDITIONS)}")
        sys.exit(1)

    store = VectorStore()
    for condition in conditions:
        collection = CONDITIONS[condition]["collection"]
        if collection and store.knowledge_count(collection) == 0:
            print(f"Collection '{collection}' is empty. Run with --ingest first.")
            sys.exit(1)

    judge_model = (
        f"openai/{args.judge_model}" if args.judge_model else run_config.litellm_model()
    )
    second_judge = f"openai/{args.second_judge}" if args.second_judge else ""

    if args.question_set == "v2":
        from evaluation.benchmark_v2 import all_questions

        questions = all_questions(include_holdout=args.include_holdout)
    else:
        questions = QUESTIONS

    if args.limit:
        questions = questions[: args.limit]
        print(f"LIMITED to {args.limit} questions, this is a smoke test not a result")

    print(f"Questions: {len(questions)} ({args.question_set})")
    print(f"Conditions: {len(conditions)}")
    print(f"Judge: {judge_model}" + (f" and {second_judge}" if second_judge else ""))
    print()

    run(conditions, judge_model, questions=questions, second_judge=second_judge)


if __name__ == "__main__":
    main()
