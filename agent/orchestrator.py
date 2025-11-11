from pydantic import BaseModel
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional
from utils.logger import logger_instance

from agent.perception import Perception
from agent.memory import Memory
from agent.reasoning import ReasoningEngine
from agent.planner import Planner
from agent.executor import Executor
from tools.tool_manager import ToolManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class OrchestrationResult(BaseModel):
    success: bool
    result: str
    strategy_used: str
    steps_executed: int = 0
    error: Optional[str] = None


class Orchestrator:
    def __init__(self, model_name="gpt-4o", agent_role=""):
        self.model_name = ""
        self.role = agent_role + "\n"
        if model_name.lower()[0:3] == "gpt":
            self.model_name = "openai/" + model_name

        self.logger = logger_instance.get_logger("orchestrator")

        self.perception = Perception()
        self.memory = Memory()
        self.tool_manager = ToolManager()
        self.reasoning_engine = ReasoningEngine(self.tool_manager)
        self.planner = Planner(model_name, agent_role)
        self.executor = Executor(model_name, agent_role)

        self.logger.info("Orchestrator initialized with all components")

    def run(self, user_input: str,
            verbose: bool = False) -> OrchestrationResult:
        try:
            if verbose:
                print("[ORCHESTRATOR] Starting processing...")
                print(f"[ORCHESTRATOR] Input: {user_input[:100]}...")

            self.logger.info(f"Processing user input: {user_input[:100]}...")

            if verbose:
                print("[PERCEPTION] Processing input...")

            perception_output = self.perception.process_input(user_input)

            if verbose:
                print(f"[PERCEPTION] Intent detected: "
                      f"{perception_output.intent}")

            self.logger.info(f"Perception completed - "
                             f"Intent: {perception_output.intent}")

            if verbose:
                print("[REASONING] Selecting strategy...")

            strategy = self.reasoning_engine.select_strategy(perception_output)

            if verbose:
                print(f"[REASONING] Selected strategy: {strategy}")

            self.logger.info(f"Selected strategy: {strategy}")

            if strategy == "plan_and_execute":
                if verbose:
                    print("[EXECUTION] Using Plan-and-Execute strategy...")
                result = self._execute_plan_and_execute(perception_output,
                                                        verbose)
            else:
                if verbose:
                    print("[EXECUTION] Using ReAct strategy...")
                result = self._execute_react(perception_output, verbose)

            if verbose:
                print("[MEMORY] Storing interaction...")

            self.memory.add_interaction(user_input, result.result)

            if verbose:
                print("[ORCHESTRATOR] Processing completed successfully")

            self.logger.info(f"Orchestration completed successfully "
                             f"using {strategy}")
            return result

        except Exception as e:
            error_msg = f"Orchestration failed: {str(e)}"
            if verbose:
                print(f"[ORCHESTRATOR] Error: {error_msg}")
            self.logger.error(error_msg)
            return OrchestrationResult(
                success=False,
                result="I encountered an error while processing your request.",
                strategy_used="error",
                error=error_msg
            )
    
    def _execute_plan_and_execute(self, perception_output,
                                  verbose: bool = False) -> OrchestrationResult:
        try:
            if verbose:
                print("[PLANNER] Creating plan...")

            available_tools = list(self.tool_manager.tools.keys())
            plan = self.planner.create_plan(perception_output, available_tools)

            if verbose:
                print(f"[PLANNER] Created plan with {len(plan.steps)} steps:")
                for i, step in enumerate(plan.steps, 1):
                    print(f"[PLANNER]   Step {i}: {step.description}")
                    if step.tool_required:
                        print(f"[PLANNER]     Tool: {step.tool_required}")

            if verbose:
                print("[EXECUTOR] Executing plan...")

            execution_result = self.executor.execute_plan(plan,
                                                          self.tool_manager,
                                                          verbose)

            if verbose:
                print(f"[EXECUTOR] Plan execution completed with "
                      f"{len(execution_result.step_results)} steps")

            return OrchestrationResult(
                success=execution_result.success,
                result=execution_result.result,
                strategy_used="plan_and_execute",
                steps_executed=len(execution_result.step_results),
                error=execution_result.error
            )

        except Exception as e:
            if verbose:
                print(f"[PLAN_AND_EXECUTE] Error: {str(e)}")
            return OrchestrationResult(
                success=False,
                result="Failed to execute plan and execute strategy.",
                strategy_used="plan_and_execute",
                error=str(e)
            )
    
    def _execute_react(self, perception_output,
                       verbose: bool = False) -> OrchestrationResult:
        try:
            if verbose:
                print("[REASONING] Starting ReAct loop...")

            result, iterations = self.reasoning_engine.react_loop(
                perception_output, self.memory, verbose)

            if verbose:
                print(f"[REASONING] ReAct loop completed in "
                      f"{iterations} iterations")

            return OrchestrationResult(
                success=True,
                result=result,
                strategy_used="react",
                steps_executed=iterations
            )

        except Exception as e:
            if verbose:
                print(f"[REACT] Error: {str(e)}")
            return OrchestrationResult(
                success=False,
                result="Failed to execute ReAct strategy.",
                strategy_used="react",
                error=str(e)
            )

    def get_system_status(self) -> Dict[str, Any]:
        return {
            "components": {
                "perception": "active",
                "memory": {
                    "short_term_entries": len(self.memory.short_term_memory),
                    "long_term_entries": len(self.memory.long_term_memory)
                },
                "reasoning_engine": "active",
                "planner": "active",
                "executor": "active",
                "tool_manager": {
                    "available_tools": len(self.tool_manager.tools),
                    "tools": list(self.tool_manager.tools.keys())
                }
            },
            "configuration": {
                "model": self.model_name,
                "role": self.role.strip()
            }
        }
    
    def reset_session(self):
        self.memory.end_current_session()
        self.memory.start_new_session()
        self.logger.info("Session reset completed")
