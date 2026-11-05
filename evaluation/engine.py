import os
from typing import List
from litellm import completion
from utils.logger import logger_instance
from utils import run_config
from evaluation import citation_validator, risk_score_check
from knowledge.rag_pipeline import RAGPipeline
from dotenv import load_dotenv

load_dotenv()

# Used when a request names no standards. Single source of truth: the web app
# records this same list as the standards a report was evaluated against.
DEFAULT_STANDARDS = [
    "ISO 27001", "SOC 2", "GDPR", "NIST CSF", "PCI DSS",
    "SBP Regulations", "FATF", "SECP Guidelines", "Pakistan AML/CFT",
]

# Each retrieved requirement is used as a company-document query, truncated so
# one long chunk does not dominate its own embedding.
REQUIREMENT_QUERY_CHARS = 1000


class EvaluationEngine:
    """Runs compliance gap analysis against uploaded company documents."""

    def __init__(self, rag_pipeline: RAGPipeline = None, knowledge_base=None):
        self.rag_pipeline = rag_pipeline or RAGPipeline()
        # Resolves a standard name to its corpus file, so each standard's
        # retrieval can be kept to its own document.
        self.knowledge_base = knowledge_base
        self.logger = logger_instance.get_logger("evaluation_engine")
        self.model_config = {
            "model": run_config.litellm_model(),
            "temperature": run_config.temperature(),
            "max_tokens": int(os.getenv("MAX_TOKENS", "6000")),
        }
        self.logger.info("EvaluationEngine initialized")

    def evaluate_compliance(
        self,
        user_id: str,
        standards: List[str] = None,
        industry: str = "",
        country: str = "",
        specific_query: str = "",
        doc_ids: List[str] = None,
        verbose: bool = False,
    ) -> str:
        """Evaluate a user's documents against the given standards and return a markdown report."""
        report_text, _ = self.evaluate_with_evidence(
            user_id=user_id,
            standards=standards,
            industry=industry,
            country=country,
            specific_query=specific_query,
            doc_ids=doc_ids,
            verbose=verbose,
        )
        return report_text

    def evaluate_with_evidence(
        self,
        user_id: str,
        standards: List[str] = None,
        industry: str = "",
        country: str = "",
        specific_query: str = "",
        doc_ids: List[str] = None,
        verbose: bool = False,
    ) -> tuple:
        """Same as evaluate_compliance, plus what the report was built from.

        The evidence holds the chunks that entered the prompt, the outcome of
        the citation and risk score checks, and each step taken, so a report
        can be traced the way a chat answer already was.
        """
        self.logger.info(
            f"Starting compliance evaluation for user: {user_id}"
        )
        if verbose:
            print(f"[EVALUATION] Starting compliance evaluation for user: {user_id}")

        if not standards:
            standards = list(DEFAULT_STANDARDS)

        if verbose:
            print(f"[EVALUATION] Standards selected ({len(standards)}): {', '.join(standards)}")

        company_query = (
            "security policies, compliance, governance, controls, "
            "risk management, data protection, access control, "
            "incident response, business continuity"
        )
        if specific_query:
            company_query = specific_query

        # one query per standard avoids crowding in combined similarity search
        if verbose:
            print("[EVALUATION] Retrieving regulatory context per standard (anti-crowding)...")
        regulatory_context, regulatory_results = self._retrieve_per_standard_context(
            standards, industry, country, verbose=verbose
        )
        requirement_texts = [r.get("content", "") for r in regulatory_results]
        if verbose:
            print(f"[EVALUATION] Retrieved {len(regulatory_context)} chars of regulatory context total")

        # Search the company documents with the retrieved requirements
        # themselves. A single generic query reached only a few sections of a
        # long policy, so gaps were reported for content that existed.
        if verbose:
            if doc_ids:
                print(f"[EVALUATION] Retrieving company documents (restricted to {len(doc_ids)} selected document(s))...")
            else:
                print("[EVALUATION] Retrieving company documents from vector store (all uploaded documents)...")
        company_queries = [company_query] + [
            text[:REQUIREMENT_QUERY_CHARS] for text in requirement_texts
        ]
        company_context, company_results = (
            self.rag_pipeline.retrieve_company_docs_for_queries_with_results(
                user_id, company_queries, doc_ids=doc_ids
            )
        )
        if verbose:
            print(
                f"[EVALUATION] Retrieved {len(company_context)} chars of company document "
                f"context from {len(company_queries)} queries"
            )

        if verbose:
            print(f"[EVALUATION] Generating structured report via {self.model_config['model']} (temperature={self.model_config['temperature']})...")
        report_text = self._generate_evaluation(
            company_context=company_context,
            regulatory_context=regulatory_context,
            standards=standards,
            industry=industry,
            country=country,
            specific_query=specific_query,
        )
        if verbose:
            print(f"[EVALUATION] Report generated ({len(report_text)} chars)")

        # The model fills the scoring table in; recompute each row from its
        # S, L and G so a wrong score, band or escalation marker is corrected
        # and listed rather than published as the rule's output.
        report_text, score_check = risk_score_check.check_and_correct(report_text)
        if verbose:
            print(
                f"[EVALUATION] Risk score check: {score_check.rows_checked} row(s), "
                f"{len(score_check.corrections)} corrected"
            )

        # The prompt asks for retrieved identifiers only, but a prompt cannot
        # guarantee it, so check each one against what was actually retrieved.
        # Pass the two contexts separately: an uploaded policy must not be able
        # to satisfy a regulatory citation.
        validation = citation_validator.validate(
            report_text,
            regulatory_context=regulatory_context,
            company_context=company_context,
        )
        report_text += risk_score_check.format_check(score_check)
        report_text += citation_validator.format_report(validation)

        self.logger.info(
            f"Citation validation: {validation.summary()}"
        )
        if verbose:
            print(
                f"[EVALUATION] Citation check: {len(validation.supported)}/"
                f"{validation.total} identifiers supported"
            )
            if validation.unsupported:
                print(
                    f"[EVALUATION] Unsupported: "
                    f"{', '.join(c.text for c in validation.unsupported)}"
                )

        self.logger.info("Compliance evaluation completed")
        if verbose:
            print("[EVALUATION] Done")

        evidence = {
            "standards": list(standards),
            "doc_ids": list(doc_ids or []),
            "retrieved": regulatory_results + company_results,
            "validation": {
                "citations": validation.summary(),
                "risk_score_check": {
                    "rows_checked": score_check.rows_checked,
                    "corrections": score_check.corrections,
                    "unparsed_rows": len(score_check.unparsed),
                },
            },
            "steps": [
                ("regulatory_retrieval", {"standards": len(standards)},
                 f"{len(regulatory_results)} chunks retrieved", bool(regulatory_results)),
                ("company_retrieval", {"queries": len(company_queries), "doc_ids": len(doc_ids or [])},
                 f"{len(company_results)} chunks retrieved", True),
                ("report_generation", {"model": self.model_config["model"]},
                 f"{len(report_text)} chars", True),
                ("risk_score_check", {},
                 f"{score_check.rows_checked} rows, {len(score_check.corrections)} corrected", True),
                ("citation_validation", {},
                 f"{len(validation.supported)}/{validation.total} identifiers supported", True),
            ],
        }
        return report_text, evidence

    def _retrieve_per_standard_context(
        self,
        standards: List[str],
        industry: str,
        country: str,
        verbose: bool = False,
    ) -> tuple:
        """Query the knowledge base once per standard to avoid similarity crowding.

        A separate query alone did not keep a standard's context to that
        standard: "ISO 27001 ... Fintech Pakistan" ranked SECP, SBP and SWIFT
        chunks above every ISO 27001 chunk. Where the standard maps to a corpus
        file, retrieval is restricted to that file.

        Returns the formatted context and the retrieved chunks themselves.
        """
        sections = []
        retrieved = []
        for std in standards:
            query = f"{std} requirements controls compliance obligations"
            if industry:
                query += f" {industry}"
            if country:
                query += f" {country}"
            source = (
                self.knowledge_base.resolve_standard_source(std)
                if self.knowledge_base else None
            )
            if source is None:
                self.logger.warning(
                    f"No corpus file matched standard '{std}'; using unrestricted retrieval"
                )
            chunk, results = self.rag_pipeline.retrieve_knowledge_with_results(
                query, source=source
            )
            # Every corpus file has chunks, so nothing back means retrieval
            # failed or the index is empty. Writing the report anyway produced
            # findings with no regulatory text behind them, saved as success.
            if not results:
                raise RuntimeError(
                    f"No regulatory context could be retrieved for '{std}'. "
                    "The knowledge base may be empty or unavailable."
                )
            retrieved.extend(results)
            if verbose:
                where = f" from {source}" if source else " (unrestricted)"
                print(f"[EVALUATION]   -> {std}: retrieved {len(chunk)} chars{where}")
            sections.append(f"=== {std} ===\n{chunk}")
        return "\n\n".join(sections), retrieved

    def _generate_evaluation(
        self,
        company_context: str,
        regulatory_context: str,
        standards: List[str],
        industry: str,
        country: str,
        specific_query: str,
    ) -> str:
        """Build the evaluation prompt and call the LLM."""

        system_prompt = """You are an expert compliance and security auditor. You are evaluating a company's security and compliance posture based on their uploaded documents against international regulatory standards.

You must produce a STRUCTURED evaluation report with the following sections:

## Executive Summary
A high-level overview of the company's compliance posture.

## Standards Coverage
Provide a status line for EACH standard listed under Standards to evaluate against, using its exact name. Classify every standard as exactly one of:
- Findings: the company documents contain evidence relevant to this standard, detailed in the sections below.
- Documentation gap: this standard is relevant to the company but the documents provide no evidence for it, so compliance cannot be demonstrated.
- Not applicable: this standard does not apply to an entity of this type; briefly say why.
Present this as a Markdown table with the columns: Standard | Status | Note. Every listed standard must appear here exactly once, so that no standard is silently dropped.

## Compliant Areas
Areas where the company meets or exceeds the standards. For each:
- Area name
- Description of compliance
- Specific standard reference (the exact clause, article, or control identifier as it appears in the regulatory context provided below, not a number you recall from general knowledge)

## Gap Analysis
Specific gaps or deficiencies found. For each gap:
- Area name
- Description of the gap
- Specific standard reference
- Risk Level (Critical / High / Medium / Low)
- Current State (what the company has)
- Required State (what the standard requires)

## Risk Assessment
Overall risk assessment based on identified gaps:
- Risk description
- Likelihood (High / Medium / Low)
- Impact (High / Medium / Low)
- Overall Risk Level
- Suggested mitigation

## Regulatory Risk Score and Prioritization
Compute a transparent Regulatory Risk Score for EVERY gap identified in the Gap Analysis using this fixed formula:

  Regulatory Risk Score = Obligation Severity (S) x Likelihood of Enforcement (L) x Adequacy Gap (G)

Where:
- Obligation Severity (S), scale 1 to 5: AML/CFT, sanctions, financial crime and customer data protection obligations = 5; core security controls such as access control, encryption and incident response = 4; governance and operational resilience = 3; reporting and record keeping = 2; purely administrative or procedural items = 1.
- Likelihood of Enforcement (L), scale 1 to 3: active regulator focus such as SBP AML/CFT = 3; Medium = 2; Low = 1.
- Adequacy Gap (G), scale 1 to 3: control or documentation entirely absent = 3; partially present = 2; minor gap = 1.

The score ranges from 1 to 45. Derive a priority band from the score:
- Score 24 or above: Immediate (Short-term action)
- Score 10 to 23: Medium-term action
- Score 9 or below: Long-term action

MANDATORY ESCALATION RULE: the multiplicative score alone can understate a severe obligation. A gap with Obligation Severity (S) of 5 scores only 5 when both Likelihood and Adequacy Gap are 1, which would place an AML/CFT or customer data obligation in the Long-term band. Therefore, any gap with S = 5 is never assigned below the Medium-term band, and any gap with S = 5 and G = 3 is always assigned the Immediate band, regardless of the computed score. Where escalation changes the band, report the computed score unchanged and add "escalated" in the Priority Band cell so the override is visible rather than hidden.

Present this as a Markdown table with the columns: Gap | Standard | S | L | G | Risk Score | Priority Band, sorted by Risk Score from highest to lowest. Always show the actual S, L and G values you used so the calculation is fully traceable and reproducible.

## Recommendations
Specific, actionable recommendations ordered by priority. For each:
- Priority number (1 = most urgent)
- Title
- Description of what to do
- Standard reference
- Expected effort (Quick Win / Short-term / Medium-term / Long-term)

CRITICAL RULES:
- Every standard listed under Standards to evaluate against MUST appear exactly once in the Standards Coverage section, marked as Findings, Documentation gap, or Not applicable. Never silently omit a listed standard. In the detailed sections such as Compliant Areas and Gap Analysis, only include a standard where it genuinely has compliant areas or gaps. Do not pad the report with empty subsections for standards that are Not applicable.
- ALWAYS cite the specific clause, article, section, control ID, or requirement identifier for EVERY finding, but ONLY at the level of granularity that actually appears in the provided regulatory context below. Do not invent a more specific sub-clause, sub-section, or sub-control number than what is explicitly written in the retrieved context, even if you recall a more granular numbering scheme from general knowledge. If the retrieved context only names a top-level clause or theme, cite it at that level rather than guessing a finer subdivision.
- Be specific and actionable in recommendations.
- Base your analysis ONLY on the provided company documents and regulatory context.
- If a relevant standard has no supporting company documentation, record it as a Documentation gap in the Standards Coverage section and recommend what the company should produce. If a standard genuinely does not apply to this entity, record it as Not applicable instead of reporting a documentation gap.
- Assign risk levels (Critical / High / Medium / Low) based on potential regulatory impact and likelihood of enforcement.
- Apply the Regulatory Risk Score formula exactly as defined. For every gap, show the S, L and G component values you used so the score is reproducible and never a subjective guess, then order the Recommendations to follow the resulting priority bands."""

        standards_list = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(standards))
        user_prompt = f"""Evaluate the following company's compliance posture.

**Standards to evaluate against (you MUST cover ALL of these)**:
{standards_list}

**Industry**: {industry or 'Not specified'}
**Country/Jurisdiction**: {country or 'Not specified'}
{f'**Specific Focus**: {specific_query}' if specific_query else ''}

--- COMPANY DOCUMENTS ---
{company_context}

--- REGULATORY KNOWLEDGE BASE (organised per standard) ---
{regulatory_context}

Produce a detailed, structured compliance evaluation report. In the Standards Coverage section, list every one of the standards above exactly once with its status of Findings, Documentation gap, or Not applicable, so that no standard is silently omitted. Do not create empty Compliant Areas or Gap Analysis subsections for standards that are Not applicable. Cite specific clause/article/section numbers for every finding. In the Regulatory Risk Score and Prioritization section, include the scoring table with the S, L and G values shown for every gap."""

        # Raise on failure. Returning an error page as report text used to get
        # it validated, saved as a report and audited as a successful run.
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
                seed=run_config.seed(),
            )
        except Exception as e:
            self.logger.error(f"Error generating evaluation: {e}")
            raise RuntimeError(
                f"The compliance evaluation could not be generated: {e}"
            ) from e
        return response.choices[0].message.content.strip()
