import json
import os
import re
from pydantic import BaseModel, field_validator
from litellm import completion
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance
from utils import run_config

load_dotenv()


def _max_plan_steps() -> int:
    """Upper limit on plan steps, from MAX_PLAN_STEPS (default 6)."""
    try:
        value = int(os.getenv("MAX_PLAN_STEPS", "6"))
    except ValueError:
        return 6
    return value if value > 0 else 6


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

    @field_validator("dependencies", mode="before")
    @classmethod
    def normalise_dependencies(cls, v):
        """Accept step numbers written as text, e.g. "2" or "step_number: 2".

        Entries without a number are skipped rather than rejecting the plan.
        """
        if not isinstance(v, list):
            return []
        numbers = []
        for item in v:
            if isinstance(item, bool):
                continue
            if isinstance(item, int):
                numbers.append(item)
            elif isinstance(item, float) and item.is_integer():
                numbers.append(int(item))
            elif isinstance(item, str):
                match = re.search(r"\d+", item)
                if match:
                    numbers.append(int(match.group()))
        return numbers


class Plan(BaseModel):
    goal: str
    steps: List[PlanStep]
    estimated_time: str = "unknown"


class Planner:
    """Creates structured step-by-step plans for user queries.

    Injects RAG context into the planning prompt so the LLM produces
    regulation-aware, citation-backed plans for compliance queries.
    """

    def __init__(self, model_name: str = ""):
        self.logger = logger_instance.get_logger("planner")
        self.model_config = {
            "model": f"openai/{model_name}" if model_name else run_config.litellm_model(),
            "temperature": run_config.temperature(),
            "max_tokens": int(os.getenv("MAX_TOKENS", "6000")),
        }

    def create_plan(
        self,
        perception_output,
        rag_context: str = "",
        conversation_context: str = "",
    ) -> Plan:
        """Generate a JSON step plan enriched with RAG context.

        Args:
            perception_output: Classified input from the Perception stage.
            rag_context: Retrieved regulatory and company document context.
            conversation_context: Recent user/agent turns, so the plan can
                resolve follow-up references (e.g. "the second gap").

        Returns:
            A Plan with one or more PlanSteps for the Executor to run.
        """
        goal = perception_output.structured_input["original_content"]
        intent = perception_output.intent

        self.logger.info(f"Creating plan for goal: {goal[:80]}...")

        history_section = ""
        if conversation_context and conversation_context.strip():
            history_section = f"""
RECENT CONVERSATION (most recent last):
Use this to interpret follow-up questions that refer back to earlier turns.

{conversation_context}
"""

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

No tools are available. Set tool_required to null for ALL steps.
{history_section}
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
                seed=run_config.seed(),
                # Request a JSON object; the fallback below handles other failures.
                # drop_params omits the setting for models without JSON mode.
                response_format={"type": "json_object"},
                drop_params=True,
            )

            raw_content = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[1]
                raw_content = raw_content.rsplit("```", 1)[0]

            plan = Plan(**json.loads(raw_content.strip()))
            # Cap the plan length: each step is a separate model call.
            limit = _max_plan_steps()
            if len(plan.steps) > limit:
                self.logger.warning(
                    f"Plan had {len(plan.steps)} steps; keeping the first {limit}"
                )
                plan.steps = plan.steps[:limit]
            # A dependency on a step that is not in the plan would stop the
            # dependent step from running.
            kept = {s.step_number for s in plan.steps}
            for s in plan.steps:
                s.dependencies = [d for d in s.dependencies if d in kept]
            self.logger.info(f"Created plan with {len(plan.steps)} steps")
            return plan

        except Exception as e:
            self.logger.error(f"Error creating plan: {e}")
            return Plan(
                goal=goal,
                steps=[PlanStep(step_number=1, description=f"Address the user's request: {goal}")],
            )
