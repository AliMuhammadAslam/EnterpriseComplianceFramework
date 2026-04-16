import os
import json
from typing import List, Optional
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
            "temperature": 0.2,
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
    ) -> str:
        """Evaluate a user's documents against the given standards and return a markdown report."""
        self.logger.info(
            f"Starting compliance evaluation for user: {user_id}"
        )

        if not standards:
            standards = [
                "ISO 27001", "SOC 2", "GDPR", "NIST CSF",
                "HIPAA", "PCI DSS", "COBIT"
            ]

        company_query = (
            "security policies, compliance, governance, controls, "
            "risk management, data protection, access control, "
            "incident response, business continuity"
        )
        if specific_query:
            company_query = specific_query

        company_context = self.rag_pipeline.retrieve_company_docs_only(
            user_id, company_query
        )

        # one query per standard avoids crowding in combined similarity search
        regulatory_context = self._retrieve_per_standard_context(
            standards, industry, country
        )

        report_text = self._generate_evaluation(
            company_context=company_context,
            regulatory_context=regulatory_context,
            standards=standards,
            industry=industry,
            country=country,
            specific_query=specific_query,
        )

        self.logger.info("Compliance evaluation completed")
        return report_text

    def _retrieve_per_standard_context(
        self,
        standards: List[str],
        industry: str,
        country: str,
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

## Compliant Areas
Areas where the company meets or exceeds the standards. For each:
- Area name
- Description of compliance
- Specific standard reference (e.g., "ISO 27001 Clause 5.2", "GDPR Article 25")

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

## Recommendations
Specific, actionable recommendations ordered by priority. For each:
- Priority number (1 = most urgent)
- Title
- Description of what to do
- Standard reference
- Expected effort (Quick Win / Short-term / Medium-term / Long-term)

CRITICAL RULES:
- You MUST include a section for EVERY standard listed in "Standards to evaluate against". Do not skip any standard, even if the retrieved context is limited — in that case note the gap explicitly.
- ALWAYS cite the specific standard clause, article, section, or requirement number for EVERY finding (e.g. "ISO 27001 Clause 6.1.2", "SBP Information Security Circular 2017 Section 3.2", "GDPR Article 32").
- Be specific and actionable in recommendations.
- Base your analysis ONLY on the provided company documents and regulatory context.
- If company documents are absent or insufficient for a standard, explicitly state "No company documentation found for this area" and recommend what should be produced.
- Assign risk levels (Critical / High / Medium / Low) based on potential regulatory impact and likelihood of enforcement."""

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

Produce a detailed, structured compliance evaluation report. You MUST explicitly address every standard listed above — include its name as a sub-heading under each section where relevant. Cite specific clause/article/section numbers for every finding."""

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
