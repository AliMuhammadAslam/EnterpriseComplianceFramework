import os
import csv
import json
import sys
import time
from datetime import datetime
from dotenv import load_dotenv
from litellm import completion

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from knowledge.rag_pipeline import RAGPipeline


# Questions are deliberately chosen to require specific numerical values,
# section identifiers, or version-specific details that a general-purpose
# LLM is unlikely to reproduce accurately without the knowledge base.
QUESTIONS = [
    {
        "id": "SBP-01",
        "standard": "SBP EMI Regulations 2019",
        "question": (
            "Under SBP EMI Regulations 2019, what is the maximum e-wallet balance "
            "limit for a Level 2 verified account, and what KYC documentation is "
            "required to reach that tier?"
        ),
        "ground_truth": (
            "The maximum e-wallet balance limit for a Level 2 (L2) verified account "
            "is PKR 500,000 under SBP EMI Regulations 2019. Level 2 requires full KYC "
            "verification with source of income documentation. There is no monthly "
            "transaction limit for L2 accounts."
        ),
    },
    {
        "id": "SBP-02",
        "standard": "SBP Branchless Banking Regulations",
        "question": (
            "What are the monthly transaction limit and maximum balance for a Level 1 "
            "(L1) branchless banking account under SBP Branchless Banking Regulations, "
            "and what verification method is required to open one?"
        ),
        "ground_truth": (
            "A Level 1 (L1) account has a monthly transaction limit of PKR 80,000 and "
            "a balance limit of PKR 400,000. Biometric verification is required to open "
            "an L1 account. This is defined in the SBP Branchless Banking Regulations "
            "(2008, amended 2016)."
        ),
    },
    {
        "id": "SBP-03",
        "standard": "SBP Data Localisation Requirements",
        "question": (
            "Under SBP data localisation requirements, what conditions must a foreign "
            "cloud provider meet to be used by an SBP-regulated entity for data storage?"
        ),
        "ground_truth": (
            "Foreign cloud providers must maintain a local data centre in Pakistan or "
            "partner with a Pakistan-based cloud node to store regulated data within "
            "Pakistani borders. Use of any cloud infrastructure (domestic or foreign) "
            "for data storage or processing requires prior SBP approval. Primary data "
            "must remain in Pakistan; replication to offshore disaster recovery sites "
            "is permitted only if the primary copy stays in-country."
        ),
    },
    {
        "id": "SBP-04",
        "standard": "SBP Regulations",
        "question": (
            "What is the data breach notification timeframe for SBP-regulated entities, "
            "and what is the threshold that triggers the obligation?"
        ),
        "ground_truth": (
            "SBP-regulated entities must notify SBP within 72 hours of discovering a "
            "personal data breach that may affect customer interests or regulatory "
            "compliance. The obligation applies to any breach that meets this threshold, "
            "as stated in the SBP customer data privacy and consent requirements."
        ),
    },
    {
        "id": "PECA-01",
        "standard": "PECA 2016",
        "question": (
            "What is the penalty for electronic fraud under Section 13 of PECA 2016, "
            "and what specific activities does this section cover?"
        ),
        "ground_truth": (
            "Section 13 of PECA 2016 (Electronic Fraud) prescribes imprisonment of up "
            "to 2 years, or a fine of up to PKR 10 million, or both. It covers using "
            "any information system to interfere with data or a system with dishonest "
            "intent, including phishing, card skimming, and unauthorized transaction "
            "manipulation."
        ),
    },
    {
        "id": "PECA-02",
        "standard": "PECA 2016",
        "question": (
            "Under Section 29 of PECA 2016, for how long can service providers be "
            "required to preserve data upon a government request?"
        ),
        "ground_truth": (
            "Under Section 29 of PECA 2016, service providers may be required to "
            "preserve specified data for up to 90 days upon a government request. "
            "Financial institutions should maintain transaction logs and system "
            "access records to meet this obligation."
        ),
    },
    {
        "id": "ISO27001-01",
        "standard": "ISO 27001",
        "question": (
            "How many Annex A controls does ISO/IEC 27001:2022 contain, how are they "
            "organised, and how does this differ from the 2013 version?"
        ),
        "ground_truth": (
            "ISO/IEC 27001:2022 contains 93 controls organised into 4 themes: "
            "Organizational Controls (A.5), People Controls (A.6), Physical Controls "
            "(A.7), and Technological Controls (A.8). The 2013 version had 114 controls "
            "organised into 14 domains/categories."
        ),
    },
    {
        "id": "ISO27001-02",
        "standard": "ISO 27001",
        "question": "What is the purpose of ISO 27001:2022 Annex A control A.5.23?",
        "ground_truth": (
            "Annex A control A.5.23 covers information security for use of cloud "
            "services. It is a new control introduced in the ISO/IEC 27001:2022 "
            "revision and falls under the Organizational Controls theme (A.5.1–A.5.37)."
        ),
    },
    {
        "id": "ISO22301-01",
        "standard": "ISO 22301",
        "question": (
            "Under ISO 22301 Clause 8.2, what three time-based recovery objectives "
            "must a Business Impact Analysis establish?"
        ),
        "ground_truth": (
            "ISO 22301 Clause 8.2 requires the Business Impact Analysis to establish: "
            "Maximum Tolerable Period of Disruption (MTPD), Recovery Time Objective "
            "(RTO), and Recovery Point Objective (RPO). These set the prioritised "
            "timeframes for resumption of critical business activities."
        ),
    },
    {
        "id": "GDPR-01",
        "standard": "GDPR",
        "question": (
            "Under GDPR, what are the two separate breach notification obligations "
            "and which specific articles govern each one?"
        ),
        "ground_truth": (
            "There are two separate obligations: (1) Article 33 requires the data "
            "controller to notify the competent supervisory authority within 72 hours "
            "of becoming aware of a breach. (2) Article 34 requires notifying the "
            "affected individuals without undue delay if the breach poses a high risk "
            "to their rights and freedoms."
        ),
    },
]


JUDGE_PROMPT = """You are evaluating an AI compliance assistant's answer to a regulatory question.

QUESTION:
{question}

GROUND TRUTH (correct answer extracted from the authoritative source document):
{ground_truth}

SYSTEM ANSWER (the response produced by the AI system being evaluated):
{answer}

Score the system answer on three metrics. Each is an integer from 1 to 5.

Citation Accuracy (1-5):
  5 = All regulatory identifiers cited (clause numbers, article numbers, section numbers, requirement numbers, specific values like PKR amounts) are correct and match the ground truth.
  4 = Mostly correct identifiers, minor imprecision.
  3 = Some correct identifiers but some missing or slightly imprecise.
  2 = Few correct identifiers; several missing or wrong.
  1 = No identifiers cited, or the identifiers cited are incorrect or fabricated.

Hallucination Rate (1-5):
  5 = No hallucinated facts. Every claim is supported by the ground truth or is a reasonable inference from it.
  4 = One minor unsupported claim, but no outright fabrication.
  3 = One or two clearly unsupported or potentially incorrect claims.
  2 = Several unsupported claims.
  1 = Significant hallucination — multiple incorrect or fabricated regulatory facts.

Answer Relevance (1-5):
  5 = Directly and completely answers the question; all key points from the ground truth are present.
  4 = Addresses the question well with most key points covered.
  3 = Partially answers; some key points are missing.
  2 = Only superficially addresses the question.
  1 = Largely off-topic or fails to address the question.

Respond ONLY with a JSON object in this exact format, no additional text:
{{"citation_accuracy": <int>, "hallucination_rate": <int>, "answer_relevance": <int>}}"""


def get_model():
    return f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}"


def call_baseline(question, model):
    response = completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a compliance and regulatory expert. Answer the question "
                    "accurately. Cite specific clause numbers, article numbers, section "
                    "references, and exact numerical values where applicable."
                ),
            },
            {"role": "user", "content": question},
        ],
        temperature=0.0,
        max_tokens=600,
    )
    return response.choices[0].message.content.strip()


def call_rag(question, rag, model):
    context = rag.retrieve_knowledge_only(question)
    response = completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a compliance expert. Use ONLY the provided reference "
                    "material to answer. Cite specific identifiers and values exactly "
                    "as they appear in the reference material.\n\n"
                    f"REFERENCE MATERIAL:\n{context}"
                ),
            },
            {"role": "user", "content": question},
        ],
        temperature=0.0,
        max_tokens=600,
    )
    return response.choices[0].message.content.strip()


def judge_answer(question, ground_truth, answer, model):
    prompt = JUDGE_PROMPT.format(
        question=question,
        ground_truth=ground_truth,
        answer=answer,
    )
    response = completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=80,
    )
    raw = response.choices[0].message.content.strip()
    # strip markdown code fences if the model wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return json.loads(raw.strip())


def run_evaluation():
    model = get_model()
    rag = RAGPipeline()

    results_dir = "evaluation/results"
    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = f"{results_dir}/results_{timestamp}.csv"
    md_path = f"{results_dir}/results_{timestamp}.md"

    conditions = ["baseline", "rag"]
    rows = []

    print(f"Running evaluation — {len(QUESTIONS)} questions x 2 conditions")
    print(f"Model: {model}\n")

    for i, q in enumerate(QUESTIONS, 1):
        print(f"[{i}/{len(QUESTIONS)}] {q['id']}  ({q['standard']})")
        row = {
            "id": q["id"],
            "standard": q["standard"],
            "question": q["question"],
        }

        for condition in conditions:
            print(f"  {condition}", end=" ... ", flush=True)
            try:
                if condition == "baseline":
                    answer = call_baseline(q["question"], model)
                else:
                    answer = call_rag(q["question"], rag, model)

                scores = judge_answer(q["question"], q["ground_truth"], answer, model)
                mean = round(
                    (
                        scores["citation_accuracy"]
                        + scores["hallucination_rate"]
                        + scores["answer_relevance"]
                    )
                    / 3,
                    2,
                )
                row[f"{condition}_citation"] = scores["citation_accuracy"]
                row[f"{condition}_hallucination"] = scores["hallucination_rate"]
                row[f"{condition}_relevance"] = scores["answer_relevance"]
                row[f"{condition}_mean"] = mean
                row[f"{condition}_answer"] = answer

                print(
                    f"CA={scores['citation_accuracy']} "
                    f"HR={scores['hallucination_rate']} "
                    f"AR={scores['answer_relevance']} "
                    f"mean={mean}"
                )

            except Exception as e:
                print(f"ERROR — {e}")
                for metric in ["citation", "hallucination", "relevance", "mean"]:
                    row[f"{condition}_{metric}"] = None
                row[f"{condition}_answer"] = f"ERROR: {e}"

            time.sleep(1)

        rows.append(row)
        print()

    _write_csv(rows, csv_path)
    _write_markdown(rows, md_path)

    print(f"Results saved:")
    print(f"  CSV:      {csv_path}")
    print(f"  Markdown: {md_path}\n")

    _print_summary(rows)


def _write_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(rows, path):
    conditions = ["baseline", "rag"]
    metrics = ["citation", "hallucination", "relevance", "mean"]

    averages = {}
    for cond in conditions:
        averages[cond] = {}
        for metric in metrics:
            vals = [
                r[f"{cond}_{metric}"]
                for r in rows
                if r.get(f"{cond}_{metric}") is not None
            ]
            averages[cond][metric] = round(sum(vals) / len(vals), 2) if vals else "N/A"

    label_map = {
        "citation": "Citation Accuracy",
        "hallucination": "Hallucination Rate (5 = none)",
        "relevance": "Answer Relevance",
        "mean": "**Mean Score**",
    }

    lines = [
        "# Quantitative Evaluation Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Questions**: {len(rows)}",
        "**Conditions**: Baseline LLM (No RAG), RAG-Enhanced LLM",
        "**Scale**: 1–5 (higher is better for all metrics)",
        "",
        "---",
        "",
        "## Summary — Average Scores",
        "",
        "| Metric | Baseline (No RAG) | RAG-Enhanced |",
        "|--------|-------------------|--------------|",
    ]

    for metric, label in label_map.items():
        lines.append(
            f"| {label} "
            f"| {averages['baseline'][metric]} "
            f"| {averages['rag'][metric]} |"
        )

    lines += ["", "---", "", "## Per-Question Breakdown", ""]

    for row in rows:
        lines.append(f"### {row['id']} — {row['standard']}")
        lines.append(f"**Question**: {row['question']}")
        lines.append("")
        lines.append(
            "| Condition | Citation Accuracy | Hallucination Rate | Answer Relevance | Mean |"
        )
        lines.append(
            "|-----------|-------------------|--------------------|------------------|------|"
        )
        for cond in conditions:
            lines.append(
                f"| {cond} "
                f"| {row.get(f'{cond}_citation', 'N/A')} "
                f"| {row.get(f'{cond}_hallucination', 'N/A')} "
                f"| {row.get(f'{cond}_relevance', 'N/A')} "
                f"| {row.get(f'{cond}_mean', 'N/A')} |"
            )
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _print_summary(rows):
    conditions = ["baseline", "rag"]
    print("=== SUMMARY (averages, 1–5 scale) ===")
    print(
        f"{'Condition':<20} {'Citation':>10} {'Hallucination':>15} {'Relevance':>12} {'Mean':>8}"
    )
    print("-" * 70)
    for cond in conditions:
        vals = {
            m: [r[f"{cond}_{m}"] for r in rows if r.get(f"{cond}_{m}") is not None]
            for m in ["citation", "hallucination", "relevance", "mean"]
        }
        avgs = {m: round(sum(v) / len(v), 2) if v else 0.0 for m, v in vals.items()}
        print(
            f"{cond:<20} {avgs['citation']:>10} {avgs['hallucination']:>15} "
            f"{avgs['relevance']:>12} {avgs['mean']:>8}"
        )


if __name__ == "__main__":
    run_evaluation()
