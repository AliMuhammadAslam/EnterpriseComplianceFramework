import json
import os
from pydantic import BaseModel, field_validator
from litellm import completion
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance

load_dotenv()


class PlanStep(BaseModel):
    step_number: int
    description: str
    tool_required: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    dependencies: List[int] = []

    @field_validator("tool_required", mode="before")
    @classmethod
    def normalise_null(cls, v):
        """Convert LLM string 'null'/'none'/'' to Python None."""
        if isinstance(v, str) and v.strip().lower() in ("null", "none", ""):
            return None
        return v


class Plan(BaseModel):
    goal: str
    steps: List[PlanStep]
    estimated_time: str = "unknown"


class Planner:
    """Creates structured step-by-step plans for user queries.

    Injects RAG context into the planning prompt so the LLM produces
    regulation-aware, citation-backed plans for compliance queries.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.logger = logger_instance.get_logger("planner")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', model_name)}",
            "temperature": float(os.getenv("TEMPERATURE", "0.3")),
            "max_tokens": int(os.getenv("MAX_TOKENS", "4000")),
        }

    def create_plan(self, perception_output, rag_context: str = "") -> Plan:
        """Generate a JSON step plan enriched with RAG context.

        Args:
            perception_output: Classified input from the Perception stage.
            rag_context: Retrieved regulatory and company document context.

        Returns:
            A Plan with one or more PlanSteps for the Executor to run.
        """
        goal = perception_output.structured_input["original_content"]
        intent = perception_output.intent

        self.logger.info(f"Creating plan for goal: {goal[:80]}...")

        rag_section = ""
        if rag_context and rag_context.strip():
            rag_section = f"""
RELEVANT KNOWLEDGE BASE CONTEXT:
The following context has been retrieved from the regulatory knowledge base
and/or company documents. Use this to create an informed, well-cited plan.

{rag_context}

For compliance queries, the plan should include steps to:
1. Analyse the retrieved regulatory context
2. Apply relevant standards and requirements
3. Cite specific standards/clauses in the response
"""

        system_message = f"""You are a compliance-aware planning agent. Create a step-by-step plan to achieve the given goal.

No tools are available — set tool_required to null for ALL steps.

{rag_section}

Respond with a JSON plan in this exact format:
{{
    "goal": "the goal to achieve",
    "steps": [
        {{
            "step_number": 1,
            "description": "detailed description of what to do",
            "tool_required": null,
            "input_data": {{}},
            "dependencies": []
        }}
    ],
    "estimated_time": "time estimate"
}}

Every step must use LLM reasoning only (tool_required: null)."""

        user_message = f"Goal: {goal}\nIntent: {intent}\nCreate a plan to achieve this goal."

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )

            raw_content = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[1]
                raw_content = raw_content.rsplit("```", 1)[0]

            plan = Plan(**json.loads(raw_content.strip()))
            self.logger.info(f"Created plan with {len(plan.steps)} steps")
            return plan

        except Exception as e:
            self.logger.error(f"Error creating plan: {e}")
            return Plan(
                goal=goal,
                steps=[PlanStep(step_number=1, description=f"Address the user's request: {goal}")],
            )
