from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
import logging
import os
from typing import Dict, Any, List
from utils.logger import logger_instance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class ExecutionResult(BaseModel):
    success: bool
    result: Any
    error: str = None
    step_results: List[Dict[str, Any]] = []


class Executor:
    def __init__(self, modelName="gpt-4o", agentRole=""):
        self.ModelName = ""
        self.Role = agentRole + "\n"
        if modelName.lower()[0:3] == "gpt":
            self.ModelName = "openai/" + modelName

        self.logger = logger_instance.get_logger("executor")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": float(os.getenv('TEMPERATURE', '0.3')),
            "max_tokens": int(os.getenv('MAX_TOKENS', '4000'))
        }

    def execute_plan(
        self,
        plan,
        tool_manager,
        verbose: bool = False,
        rag_context: str = "",
    ) -> ExecutionResult:
        """Execute a plan step by step with RAG context available."""
        self.logger.info(f"Executing plan with {len(plan.steps)} steps")

        step_results = []
        overall_success = True
        final_result = None

        try:
            for step in plan.steps:
                if verbose:
                    print(
                        f"[EXECUTOR] Executing step {step.step_number}: "
                        f"{step.description}"
                    )

                self.logger.info(
                    f"Executing step {step.step_number}: {step.description}"
                )

                if not self._check_dependencies(step, step_results):
                    error_msg = (
                        f"Dependencies not met for step {step.step_number}"
                    )
                    if verbose:
                        print(f"[EXECUTOR] {error_msg}")
                    self.logger.error(error_msg)
                    step_results.append({
                        "step_number": step.step_number,
                        "success": False,
                        "error": error_msg,
                    })
                    overall_success = False
                    continue

                step_result = self._execute_step(
                    step, tool_manager, step_results, verbose,
                    rag_context=rag_context,
                )
                step_results.append(step_result)

                if not step_result["success"]:
                    overall_success = False
                    if verbose:
                        print(
                            f"[EXECUTOR] Step {step.step_number} failed: "
                            f"{step_result.get('error')}"
                        )
                    self.logger.error(
                        f"Step {step.step_number} failed: "
                        f"{step_result.get('error')}"
                    )
                else:
                    if verbose:
                        result_preview = str(step_result['result'])[:100]
                        print(
                            f"[EXECUTOR] Step {step.step_number} completed: "
                            f"{result_preview}..."
                        )
                    self.logger.info(
                        f"Step {step.step_number} completed successfully"
                    )

            final_result = self._compile_final_result(
                step_results, plan.goal, rag_context=rag_context
            )

            if verbose:
                print("[EXECUTOR] Final result compiled")

            return ExecutionResult(
                success=overall_success,
                result=final_result,
                step_results=step_results,
            )

        except Exception as e:
            error_msg = f"Error executing plan: {e}"
            if verbose:
                print(f"[EXECUTOR] {error_msg}")
            self.logger.error(error_msg)
            return ExecutionResult(
                success=False,
                result=None,
                error=str(e),
                step_results=step_results,
            )

    def _execute_step(
        self,
        step,
        tool_manager,
        previous_results: List[Dict],
        verbose: bool = False,
        rag_context: str = "",
    ) -> Dict[str, Any]:
        try:
            if step.tool_required:
                if verbose:
                    print(f"[EXECUTOR] Using tool: {step.tool_required}")

                tool_input = step.input_data or {}

                tool_result = tool_manager.execute_tool(
                    step.tool_required, tool_input
                )

                if tool_result.success:
                    if verbose:
                        print(
                            f"[TOOL] {step.tool_required} succeeded: "
                            f"{str(tool_result.result)[:100]}..."
                        )
                    return {
                        "step_number": step.step_number,
                        "success": True,
                        "result": tool_result.result,
                        "tool_used": step.tool_required,
                    }
                else:
                    if verbose:
                        print(
                            f"[TOOL] {step.tool_required} failed: "
                            f"{tool_result.error}"
                        )
                    # If the tool simply doesn't exist, fall back to LLM
                    # rather than failing the step entirely
                    if tool_result.error and "not found" in tool_result.error:
                        self.logger.warning(
                            f"Tool '{step.tool_required}' not found, "
                            f"falling back to LLM reasoning"
                        )
                        if verbose:
                            print(
                                f"[EXECUTOR] Tool not found, "
                                f"falling back to LLM reasoning"
                            )
                        llm_result = self._execute_with_llm(
                            step, previous_results, rag_context=rag_context
                        )
                        return {
                            "step_number": step.step_number,
                            "success": True,
                            "result": llm_result,
                            "tool_used": None,
                        }
                    return {
                        "step_number": step.step_number,
                        "success": False,
                        "error": tool_result.error,
                        "tool_used": step.tool_required,
                    }
            else:
                if verbose:
                    print("[EXECUTOR] Using LLM reasoning for step")

                llm_result = self._execute_with_llm(
                    step, previous_results, rag_context=rag_context
                )

                if verbose:
                    print(
                        f"[LLM] Reasoning completed: "
                        f"{str(llm_result)[:100]}..."
                    )

                return {
                    "step_number": step.step_number,
                    "success": True,
                    "result": llm_result,
                    "tool_used": None,
                }

        except Exception as e:
            if verbose:
                print(f"[EXECUTOR] Step execution error: {str(e)}")
            return {
                "step_number": step.step_number,
                "success": False,
                "error": str(e),
            }

    def _execute_with_llm(
        self,
        step,
        previous_results: List[Dict],
        rag_context: str = "",
    ) -> str:
        """Execute a step using LLM reasoning with RAG context."""
        context = ""
        if previous_results:
            context = "Previous results:\n"
            for result in previous_results[-3:]:
                if result["success"]:
                    context += (
                        f"Step {result['step_number']}: {result['result']}\n"
                    )

        # Inject RAG context for compliance-aware reasoning
        rag_section = ""
        if rag_context:
            rag_section = f"""
RELEVANT REFERENCE MATERIAL:
{rag_context}

When answering, cite specific standards, clauses, or articles where applicable.
"""

        system_message = f"""You are an AI assistant specializing in compliance, security, and governance advisory.

You have access to a regulatory knowledge base and company documents. Use the provided reference material to give accurate, well-cited responses.

{rag_section}

Provide clear, specific, and actionable results. If the problem requires calculation, show your work. If it requires analysis, explain your reasoning with references to specific standards or regulations where applicable."""

        user_message = f"{context}\nSolve this problem: {step.description}"

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=self.model_config["max_tokens"],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error solving problem with LLM: {str(e)}"

    def _check_dependencies(
        self, step, completed_steps: List[Dict]
    ) -> bool:
        if not step.dependencies:
            return True

        completed_step_numbers = {
            result["step_number"]
            for result in completed_steps
            if result["success"]
        }

        return all(
            dep in completed_step_numbers for dep in step.dependencies
        )

    def _compile_final_result(
        self,
        step_results: List[Dict],
        goal: str,
        rag_context: str = "",
    ) -> str:
        """Compile final result with RAG-aware summarization."""
        successful_results = [
            result
            for result in step_results
            if result["success"] and result.get("result")
        ]

        if not successful_results:
            return "I was unable to complete the requested task."

        all_data = ""
        for result in successful_results:
            step_result = result["result"]
            if isinstance(step_result, list):
                for item in step_result:
                    if isinstance(item, dict):
                        title = item.get('title', '')
                        snippet = item.get('snippet', '')
                        if title and snippet:
                            all_data += f"{title}: {snippet}\n"
            else:
                all_data += f"{step_result}\n"

        # Build RAG-aware summarization prompt
        rag_section = ""
        if rag_context:
            rag_section = f"""
REFERENCE MATERIAL:
{rag_context}
"""

        try:
            system_message = f"""You are a compliance and governance specialist summarizing analysis results.

{rag_section}

Create a clear, comprehensive answer that directly addresses what the user asked for.
- For compliance/regulatory questions: cite specific standards, clauses, and articles
- For general questions: focus on key facts and information
- Structure your response with clear sections if appropriate
- Do not mention internal processing steps"""

            user_message = f"""Original question: {goal}

Analysis results and data:
{all_data}

Provide a direct, informative answer to the user's question."""

            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=self.model_config["max_tokens"],
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            self.logger.error(f"Error creating summary: {e}")
            return f"Based on the analysis: {all_data[:500]}..."
