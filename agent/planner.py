from pydantic import BaseModel, field_validator
from litellm import completion
from dotenv import load_dotenv
import logging
import os
from typing import List, Dict, Any, Optional
from utils.logger import logger_instance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    def __init__(self, modelName="gpt-4o", agentRole=""):
        self.ModelName = ""
        self.Role = agentRole + "\n"
        if modelName.lower()[0:3] == "gpt":
            self.ModelName = "openai/" + modelName

        self.logger = logger_instance.get_logger("planner")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": float(os.getenv('TEMPERATURE', '0.3')),
            "max_tokens": int(os.getenv('MAX_TOKENS', '4000'))
        }

    def create_plan(
        self,
        perception_output,
        available_tools: List[str] = None,
        rag_context: str = "",
    ) -> Plan:
        """Create a structured plan, using RAG context for compliance queries.
        
        The RAG context is injected into the planning prompt so the LLM
        can create more informed, regulation-aware plans.
        """
        goal = perception_output.structured_input["original_content"]
        intent = perception_output.intent

        self.logger.info(f"Creating plan for goal: {goal}")

        tools_description = ""
        if available_tools:
            tools_description = (
                f"Available tools: {', '.join(available_tools)}"
            )
        else:
            tools_description = (
                "No tools are available. "
                "You MUST set tool_required to null for ALL steps."
            )

        # Build RAG context section for the prompt
        rag_section = ""
        if rag_context and rag_context.strip():
            rag_section = f"""
RELEVANT KNOWLEDGE BASE CONTEXT:
The following context has been retrieved from the regulatory knowledge base 
and/or company documents. Use this information to create a more informed plan.

{rag_context}

IMPORTANT: When the query is about compliance, security, or governance, 
your plan should include steps to:
1. Analyze the retrieved regulatory context
2. Apply relevant standards and requirements
3. Cite specific standards/clauses in the response
"""

        system_message = f"""You are a compliance-aware planning agent. Create a detailed step-by-step plan to achieve the given goal.

{tools_description}

{rag_section}

Respond with a JSON plan in this format:
{{
    "goal": "the goal to achieve",
    "steps": [
        {{
            "step_number": 1,
            "description": "detailed description of the step",
            "tool_required": null,
            "input_data": {{}},
            "dependencies": []
        }}
    ],
    "estimated_time": "time estimate"
}}

For compliance and regulatory questions, the plan should focus on analyzing
the retrieved knowledge and producing comprehensive, well-cited responses.
For all queries, every step must use LLM reasoning only (tool_required: null)."""

        user_message = (
            f"Goal: {goal}\nIntent: {intent}\n"
            f"Create a plan to achieve this goal."
        )

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=self.model_config["max_tokens"]
            )

            import json
            raw_content = response.choices[0].message.content.strip()
            # Handle markdown code blocks in response
            if raw_content.startswith("```"):
                raw_content = raw_content.split("\n", 1)[1]
                raw_content = raw_content.rsplit("```", 1)[0]
            plan_data = json.loads(raw_content.strip())
            plan = Plan(**plan_data)

            self.logger.info(f"Created plan with {len(plan.steps)} steps")
            return plan

        except Exception as e:
            self.logger.error(f"Error creating plan: {e}")
            return Plan(
                goal=goal,
                steps=[
                    PlanStep(
                        step_number=1,
                        description=(
                            f"Address the user's request: {goal}"
                        ),
                        tool_required=None,
                    )
                ],
            )

    def adapt_plan(self, current_plan: Plan, new_information: str) -> Plan:
        self.logger.info("Adapting plan based on new information")

        system_message = (
            "You are adapting an existing plan based on new information. "
            "Modify the plan as needed while keeping successful steps intact."
        )

        user_message = (
            f"Current plan: {current_plan.model_dump()}\n"
            f"New information: {new_information}\n\n"
            f"Provide an updated plan in the same JSON format."
        )

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=self.model_config["max_tokens"]
            )

            import json
            plan_data = json.loads(
                response.choices[0].message.content.strip()
            )
            adapted_plan = Plan(**plan_data)

            self.logger.info("Plan adapted successfully")
            return adapted_plan

        except Exception as e:
            self.logger.error(f"Error adapting plan: {e}")
            return current_plan

