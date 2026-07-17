import os
from typing import List
from datetime import datetime
from litellm import completion
from utils.logger import logger_instance
from knowledge.rag_pipeline import RAGPipeline
from dotenv import load_dotenv

load_dotenv()


class EvaluationEngine:
    """Runs compliance gap analysis against uploaded company documents."""

    def __init__(self, rag_pipeline: RAGPipeline = None):
        self.rag_pipeline = rag_pipeline or RAGPipeline()
        self.logger = logger_instance.get_logger("evaluation_engine")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": 0,
            "max_tokens": int(os.getenv("MAX_TOKENS", "4000")),
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
        self.logger.info(
            f"Starting compliance evaluation for user: {user_id}"
        )
        if verbose:
            print(f"[EVALUATION] Starting compliance evaluation for user: {user_id}")

        if not standards:
            standards = [
                "ISO 27001", "SOC 2", "GDPR", "NIST CSF", "PCI DSS",
                "SBP Regulations", "FATF", "SECP Guidelines", "Pakistan AML/CFT",
            ]

        if verbose:
            print(f"[EVALUATION] Standards selected ({len(standards)}): {', '.join(standards)}")

        company_query = (
            "security policies, compliance, governance, controls, "
            "risk management, data protection, access control, "
            "incident response, business continuity"
        )
        if specific_query:
            company_query = specific_query

        if verbose:
            if doc_ids:
                print(f"[EVALUATION] Retrieving company documents (restricted to {len(doc_ids)} selected document(s))...")
            else:
                print("[EVALUATION] Retrieving company documents from vector store (all uploaded documents)...")
        company_context = self.rag_pipeline.retrieve_company_docs_only(
            user_id, company_query, doc_ids=doc_ids
        )
        if verbose:
            print(f"[EVALUATION] Retrieved {len(company_context)} chars of company document context")

        # one query per standard avoids crowding in combined similarity search
        if verbose:
            print("[EVALUATION] Retrieving regulatory context per standard (anti-crowding)...")
        regulatory_context = self._retrieve_per_standard_context(
            standards, industry, country, verbose=verbose
        )
        if verbose:
            print(f"[EVALUATION] Retrieved {len(regulatory_context)} chars of regulatory context total")

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

        self.logger.info("Compliance evaluation completed")
        if verbose:
            print("[EVALUATION] Done")
        return report_text

    def _retrieve_per_standard_context(
        self,
        standards: List[str],
        industry: str,
        country: str,
        verbose: bool = False,
    ) -> str:
        """Query the knowledge base once per standard to avoid similarity crowding."""
        sections = []
        for std in standards:
            query = f"{std} requirements controls compliance obligations"
            if industry:
                query += f" {industry}"
            if country:
                query += f" {country}"
            chunk = self.rag_pipeline.retrieve_knowledge_only(query)
            if verbose:
                print(f"[EVALUATION]   -> {std}: retrieved {len(chunk)} chars")
            sections.append(f"=== {std} ===\n{chunk}")
        return "\n\n".join(sections)

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

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            self.logger.error(f"Error generating evaluation: {e}")
            return (
                f"# Evaluation Error\n\n"
                f"An error occurred while generating the compliance "
                f"evaluation report: {str(e)}\n\n"
                f"Please ensure your API key is valid and try again."
            )
