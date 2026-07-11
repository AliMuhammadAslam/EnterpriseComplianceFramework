from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
import os
from typing import Dict, Any
from utils.logger import logger_instance

load_dotenv()


class PerceptionOutput(BaseModel):
    """Result of classifying a user's input."""
    structured_input: Dict[str, Any]
    intent: str


class Perception:
    """Classifies user input into one of six intent categories using the LLM,
    with keyword fallback if the LLM call fails."""

    VALID_INTENTS = [
        "compliance_evaluation",
        "document_query",
        "information_seeking",
        "problem_solving",
        "planning",
        "general_query",
    ]

    def __init__(self):
        self.logger = logger_instance.get_logger("perception")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": 0.1,
            "max_tokens": 20,
        }

    def process_input(self, raw_input: str, source: str = "user") -> PerceptionOutput:
        """Classify raw user input and return a structured PerceptionOutput."""
        self.logger.info(f"Processing input from {source}: {raw_input[:100]}...")

        intent = self._detect_intent(raw_input)

        output = PerceptionOutput(
            structured_input={"original_content": raw_input, "source": source},
            intent=intent,
        )

        self.logger.info(f"Input processed. Intent: {intent}")
        return output

    def _detect_intent(self, content: str) -> str:
        """Classify intent via LLM, falling back to keyword matching on error."""
        try:
            system_message = (
                "Classify the user's request into exactly one of these categories:\n\n"
                "- compliance_evaluation: Requests to evaluate, audit, or assess "
                "compliance, security posture, or governance\n"
                "- document_query: Questions about uploaded documents, policies, "
                "or company-specific content\n"
                "- information_seeking: Requests for facts, definitions, or research "
                "about regulations/standards\n"
                "- problem_solving: Requires reasoning, analysis, or solving problems\n"
                "- planning: Requests for step-by-step procedures or plans\n"
                "- general_query: Casual conversation or greetings\n\n"
                "Respond with only the category name."
            )

            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": f"Classify this request: {content}"},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )

            intent = response.choices[0].message.content.strip().lower()
            return intent if intent in self.VALID_INTENTS else self._fallback_intent_detection(content)

        except Exception as e:
            self.logger.error(f"LLM intent detection failed: {e}")
            return self._fallback_intent_detection(content)

    def _fallback_intent_detection(self, content: str) -> str:
        """Keyword-based intent classification used when LLM is unavailable."""
        content_lower = content.lower()

        compliance_keywords = [
            "compliance", "audit", "evaluate", "assessment", "gap analysis",
            "iso 27001", "soc 2", "gdpr", "pci dss", "nist",
            "sbp", "secp", "aml", "cft", "fatf", "peca",
            "security posture", "governance", "regulation", "standard",
        ]
        if any(kw in content_lower for kw in compliance_keywords):
            return "compliance_evaluation"

        document_keywords = [
            "uploaded", "document", "policy", "our company",
            "my organization", "company document",
        ]
        if any(kw in content_lower for kw in document_keywords):
            return "document_query"

        if any(w in content_lower for w in ["search", "find", "what is", "who is", "define"]):
            return "information_seeking"
        if any(w in content_lower for w in ["plan", "steps", "how to", "procedure"]):
            return "planning"
        if any(w in content_lower for w in ["how", "solve", "fix", "calculate", "determine", "figure out"]):
            return "problem_solving"

        return "general_query"
