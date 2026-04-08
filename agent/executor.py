import os
from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
from typing import Dict, Any, List
from utils.logger import logger_instance

load_dotenv()


class ExecutionResult(BaseModel):
    success: bool
    result: Any
    error: str = None
    step_results: List[Dict[str, Any]] = []


class Executor:
    """Executes a Plan step by step using LLM reasoning.

    Each step is processed by the LLM with the RAG context injected
    into the system prompt, so responses are grounded in retrieved
    regulatory and company document content.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.logger = logger_instance.get_logger("executor")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', model_name)}",
            "temperature": float(os.getenv("TEMPERATURE", "0.3")),
            "max_tokens": int(os.getenv("MAX_TOKENS", "4000")),
        }

    def execute_plan(
        self, plan, verbose: bool = False, rag_context: str = ""
    ) -> ExecutionResult:
        """Execute each step of a plan sequentially.

        Args:
            plan: The Plan produced by the Planner.
            verbose: If True, print step-by-step progress to stdout.
            rag_context: Retrieved context to inject into every LLM call.

        Returns:
            ExecutionResult with the compiled final answer.
        """
        self.logger.info(f"Executing plan with {len(plan.steps)} steps")

        step_results = []
        overall_success = True

        for step in plan.steps:
            if verbose:
                print(f"[EXECUTOR] Step {step.step_number}: {step.description}")

            self.logger.info(f"Executing step {step.step_number}: {step.description}")

            if not self._dependencies_met(step, step_results):
                error_msg = f"Dependencies not met for step {step.step_number}"
                self.logger.error(error_msg)
                step_results.append({"step_number": step.step_number, "success": False, "error": error_msg})
                overall_success = False
                continue

            result_text = self._execute_with_llm(step, step_results, rag_context)
            step_results.append({"step_number": step.step_number, "success": True, "result": result_text})

            if verbose:
                print(f"[EXECUTOR] Step {step.step_number} complete: {result_text[:100]}...")

            self.logger.info(f"Step {step.step_number} completed successfully")

        final_result = self._compile_final_result(step_results, plan.goal, rag_context)

        if verbose:
            print("[EXECUTOR] Final result compiled")

        return ExecutionResult(
            success=overall_success,
            result=final_result,
            step_results=step_results,
        )

    def _execute_with_llm(
        self, step, previous_results: List[Dict], rag_context: str = ""
    ) -> str:
        """Run a single plan step through the LLM with RAG context."""
        prior_context = ""
        if previous_results:
            prior_context = "Previous steps:\n"
            for r in previous_results[-3:]:
                if r.get("success"):
                    prior_context += f"Step {r['step_number']}: {r['result']}\n"

        rag_section = ""
        if rag_context:
            rag_section = f"""
RELEVANT REFERENCE MATERIAL:
{rag_context}

Cite specific standards, clauses, or articles where applicable.
"""

        system_message = f"""You are an AI assistant specialising in compliance, security, and governance.

Use the provided reference material to give accurate, well-cited responses.
{rag_section}
Provide clear, specific, and actionable results. Cite relevant standards or regulations where applicable."""

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": f"{prior_context}\nTask: {step.description}"},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error executing step: {str(e)}"

    def _dependencies_met(self, step, completed_steps: List[Dict]) -> bool:
        """Return True if all declared dependencies have completed successfully."""
        if not step.dependencies:
            return True
        completed = {r["step_number"] for r in completed_steps if r.get("success")}
        return all(dep in completed for dep in step.dependencies)

    def _compile_final_result(
        self, step_results: List[Dict], goal: str, rag_context: str = ""
    ) -> str:
        """Summarise all step outputs into a single coherent answer."""
        successful = [r for r in step_results if r.get("success") and r.get("result")]

        if not successful:
            return "I was unable to complete the requested task."

        all_data = "\n".join(str(r["result"]) for r in successful)

        rag_section = f"\nREFERENCE MATERIAL:\n{rag_context}\n" if rag_context else ""

        system_message = f"""You are a compliance and governance specialist summarising analysis results.
{rag_section}
Write a clear, comprehensive answer that directly addresses what the user asked.
- For compliance/regulatory questions: cite specific standards, clauses, and articles
- Structure your response with clear sections where appropriate
- Do not mention internal processing steps"""

        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": f"Question: {goal}\n\nAnalysis:\n{all_data}\n\nProvide a direct, informative answer."},
                ],
                temperature=self.model_config["temperature"],
                max_tokens=self.model_config["max_tokens"],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            self.logger.error(f"Error compiling final result: {e}")
            return f"Based on the analysis: {all_data[:500]}..."
