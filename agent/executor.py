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
    """Runs a Plan step by step, injecting RAG context into each LLM call."""

    def __init__(self, model_name: str = "gpt-4o"):
        self.logger = logger_instance.get_logger("executor")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', model_name)}",
            "temperature": float(os.getenv("TEMPERATURE", "0.0")),
            "max_tokens": int(os.getenv("MAX_TOKENS", "6000")),
        }

    def execute_plan(
        self,
        plan,
        verbose: bool = False,
        rag_context: str = "",
        conversation_context: str = "",
    ) -> ExecutionResult:
        """Execute plan steps sequentially and return a compiled result."""
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

            result_text = self._execute_with_llm(
                step, step_results, rag_context, conversation_context
            )
            step_results.append({"step_number": step.step_number, "success": True, "result": result_text})

            if verbose:
                print(f"[EXECUTOR] Step {step.step_number} complete: {result_text[:100]}...")

            self.logger.info(f"Step {step.step_number} completed successfully")

        final_result = self._compile_final_result(
            step_results, plan.goal, rag_context, conversation_context
        )

        if verbose:
            print("[EXECUTOR] Final result compiled")

        return ExecutionResult(
            success=overall_success,
            result=final_result,
            step_results=step_results,
        )

    def _execute_with_llm(
        self,
        step,
        previous_results: List[Dict],
        rag_context: str = "",
        conversation_context: str = "",
    ) -> str:
        """Send a single plan step to the LLM with accumulated context."""
        prior_context = ""
        if previous_results:
            prior_context = "Previous steps:\n"
            for r in previous_results[-3:]:
                if r.get("success"):
                    prior_context += f"Step {r['step_number']}: {r['result']}\n"

        history_section = ""
        if conversation_context:
            history_section = (
                f"\nRECENT CONVERSATION (for resolving follow-up references):\n"
                f"{conversation_context}\n"
            )

        rag_section = ""
        if rag_context:
            rag_section = f"""
RELEVANT REFERENCE MATERIAL:
{rag_context}

Cite specific standards, clauses, or articles where applicable.
"""

        system_message = f"""You are an AI assistant specialising in compliance, security, and governance.

Use the provided reference material to give accurate, well-cited responses.
{history_section}{rag_section}
Provide clear, specific, and actionable results. Citation rules:
- Use ONLY the control numbers, clause numbers, article numbers, and section identifiers that appear in the provided reference material above. Do not rely on your training knowledge for specific identifiers — standards are versioned and numbering changes between versions.
- Every requirement or control you mention must include its identifier exactly as it appears in the reference material (e.g. the clause number, article number, control ID, or section reference).
- If the reference material does not contain a specific identifier for something, say so explicitly rather than inventing one."""

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
        """Check that all declared step dependencies have already succeeded."""
        if not step.dependencies:
            return True
        completed = {r["step_number"] for r in completed_steps if r.get("success")}
        return all(dep in completed for dep in step.dependencies)

    def _compile_final_result(
        self,
        step_results: List[Dict],
        goal: str,
        rag_context: str = "",
        conversation_context: str = "",
    ) -> str:
        """Combine all step outputs into a single final answer."""
        successful = [r for r in step_results if r.get("success") and r.get("result")]

        if not successful:
            return "I was unable to complete the requested task."

        all_data = "\n".join(str(r["result"]) for r in successful)

        rag_section = f"\nREFERENCE MATERIAL:\n{rag_context}\n" if rag_context else ""
        history_section = (
            f"\nRECENT CONVERSATION (for resolving follow-up references):\n"
            f"{conversation_context}\n"
            if conversation_context else ""
        )

        system_message = f"""You are a compliance and governance specialist summarising analysis results.
{history_section}{rag_section}
Write a clear, comprehensive answer that directly addresses what the user asked.
- Structure your response with clear sections where appropriate
- Do not mention internal processing steps
- If the context indicates that no company documents have been uploaded, explicitly tell the user that your response is based solely on the regulatory knowledge base and that uploading company documents will enable document-specific analysis
- Citation rule: use ONLY the control IDs, clause numbers, article numbers, and section references that appear in the provided reference material. Standards are versioned — do not substitute numbering from your training knowledge. If no identifier is present in the reference material, state that explicitly."""

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
