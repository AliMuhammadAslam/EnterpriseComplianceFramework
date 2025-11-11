from pydantic import BaseModel
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

class Plan(BaseModel):
    goal: str
    steps: List[PlanStep]
    estimated_time: str = "unknown"

class Planner:
    def __init__(self, modelName="gpt-4o", agentRole=""):
        self.ModelName = ""
        self.Role = (
            agentRole + "\n"
        )
        if modelName.lower()[0:3] == "gpt":
            self.ModelName = "openai/" + modelName
        
        self.logger = logger_instance.get_logger("planner")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": float(os.getenv('TEMPERATURE', '0.3')),
            "max_tokens": int(os.getenv('MAX_TOKENS', '1000'))
        }

    def create_plan(self, perception_output, available_tools: List[str] = None) -> Plan:
        goal = perception_output.structured_input["original_content"]
        intent = perception_output.intent
        
        self.logger.info(f"Creating plan for goal: {goal}")
        
        tools_description = ""
        if available_tools:
            tools_description = f"Available tools: {', '.join(available_tools)}"
        
        system_message = f"""You are a planning agent. Create a detailed step-by-step plan to achieve the given goal.
        
{tools_description}

Respond with a JSON plan in this format:
{{
    "goal": "the goal to achieve",
    "steps": [
        {{
            "step_number": 1,
            "description": "detailed description of the step",
            "tool_required": "tool_name or null",
            "input_data": {{}},
            "dependencies": []
        }}
    ],
    "estimated_time": "time estimate"
}}"""

        user_message = f"Goal: {goal}\nIntent: {intent}\nCreate a plan to achieve this goal."
        
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            import json
            plan_data = json.loads(response.choices[0].message.content.strip())
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
                        description=f"Address the user's request: {goal}",
                        tool_required=self._suggest_tool_for_intent(intent)
                    )
                ]
            )

    def adapt_plan(self, current_plan: Plan, new_information: str) -> Plan:
        self.logger.info("Adapting plan based on new information")
        
        system_message = """You are adapting an existing plan based on new information. 
        Modify the plan as needed while keeping successful steps intact."""
        
        user_message = f"""Current plan: {current_plan.dict()}
        New information: {new_information}
        
        Provide an updated plan in the same JSON format."""
        
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            import json
            plan_data = json.loads(response.choices[0].message.content.strip())
            adapted_plan = Plan(**plan_data)
            
            self.logger.info("Plan adapted successfully")
            return adapted_plan
            
        except Exception as e:
            self.logger.error(f"Error adapting plan: {e}")
            return current_plan

    def _suggest_tool_for_intent(self, intent: str) -> str:
        tool_mapping = {
            "problem_solving": "calculator",
            "information_seeking": "web_search",
            "planning": None,
            "general_query": None
        }
        return tool_mapping.get(intent)
