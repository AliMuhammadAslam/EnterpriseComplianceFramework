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
            "max_tokens": int(os.getenv('MAX_TOKENS', '500'))
        }

    def execute_plan(self, plan, tool_manager, verbose: bool = False) -> ExecutionResult:
        self.logger.info(f"Executing plan with {len(plan.steps)} steps")
        
        step_results = []
        overall_success = True
        final_result = None
        
        try:
            for step in plan.steps:
                if verbose:
                    print(f"[EXECUTOR] Executing step {step.step_number}: {step.description}")
                
                self.logger.info(f"Executing step {step.step_number}: {step.description}")
                
                if not self._check_dependencies(step, step_results):
                    error_msg = f"Dependencies not met for step {step.step_number}"
                    if verbose:
                        print(f"[EXECUTOR] {error_msg}")
                    self.logger.error(error_msg)
                    step_results.append({
                        "step_number": step.step_number,
                        "success": False,
                        "error": error_msg
                    })
                    overall_success = False
                    continue
                
                step_result = self._execute_step(step, tool_manager, step_results, verbose)
                step_results.append(step_result)
                
                if not step_result["success"]:
                    overall_success = False
                    if verbose:
                        print(f"[EXECUTOR] Step {step.step_number} failed: {step_result.get('error')}")
                    self.logger.error(f"Step {step.step_number} failed: {step_result.get('error')}")
                else:
                    if verbose:
                        print(f"[EXECUTOR] Step {step.step_number} completed: {str(step_result['result'])[:100]}...")
                    self.logger.info(f"Step {step.step_number} completed successfully")
                
            final_result = self._compile_final_result(step_results, plan.goal)
            
            if verbose:
                print(f"[EXECUTOR] Final result compiled")
            
            return ExecutionResult(
                success=overall_success,
                result=final_result,
                step_results=step_results
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
                step_results=step_results
            )
    
    def _execute_step(self, step, tool_manager, previous_results: List[Dict], verbose: bool = False) -> Dict[str, Any]:
        try:
            if step.tool_required:
                if verbose:
                    print(f"[EXECUTOR] Using tool: {step.tool_required}")
                
                tool_input = step.input_data or {}
                
                if not tool_input:
                    tool_input = self._generate_tool_input(step, previous_results)
                    if verbose:
                        print(f"[EXECUTOR] Generated tool input: {tool_input}")
                
                tool_result = tool_manager.execute_tool(step.tool_required, tool_input)
                
                if tool_result.success:
                    if verbose:
                        print(f"[TOOL] {step.tool_required} succeeded: {str(tool_result.result)[:100]}...")
                    return {
                        "step_number": step.step_number,
                        "success": True,
                        "result": tool_result.result,
                        "tool_used": step.tool_required
                    }
                else:
                    if verbose:
                        print(f"[TOOL] {step.tool_required} failed: {tool_result.error}")
                    return {
                        "step_number": step.step_number,
                        "success": False,
                        "error": tool_result.error,
                        "tool_used": step.tool_required
                    }
            else:
                if verbose:
                    print(f"[EXECUTOR] Using LLM reasoning for step")
                
                llm_result = self._execute_with_llm(step, previous_results)
                
                if verbose:
                    print(f"[LLM] Reasoning completed: {str(llm_result)[:100]}...")
                
                return {
                    "step_number": step.step_number,
                    "success": True,
                    "result": llm_result,
                    "tool_used": None
                }
                
        except Exception as e:
            if verbose:
                print(f"[EXECUTOR] Step execution error: {str(e)}")
            return {
                "step_number": step.step_number,
                "success": False,
                "error": str(e)
            }
    
    def _generate_tool_input(self, step, previous_results: List[Dict]) -> Dict[str, Any]:
        if step.tool_required == "calculator":
            try:
                system_message = """Convert the problem or calculation request into a simple mathematical expression that can be evaluated.

Only return the mathematical expression, nothing else."""

                user_message = f"Convert this to a mathematical expression: {step.description}"
                
                response = completion(
                    model=self.model_config["model"],
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=0.1,
                    max_tokens=100
                )
                
                expression = response.choices[0].message.content.strip()
                import re
                expression = re.sub(r'[^0-9\+\-\*/\(\)\.\s\*]', '', expression)
                expression = expression.strip()
                
                if expression and any(op in expression for op in "+-*/"): 
                    return {"expression": expression}
                else:
                    numbers = re.findall(r'\d+(?:\.\d+)?', step.description)
                    if len(numbers) >= 2:
                        return {"expression": " + ".join(numbers)}
                    
            except Exception as e:
                self.logger.error(f"Error generating calculator input: {e}")
            
            return {"expression": "0"}
            
        elif step.tool_required == "web_search":
            query = step.description.replace("search for", "").replace("find", "").strip()
            return {"query": query}
        
        return {}
    
    def _execute_with_llm(self, step, previous_results: List[Dict]) -> str:
        context = ""
        if previous_results:
            context = "Previous results:\n"
            for result in previous_results[-3:]:
                if result["success"]:
                    context += f"Step {result['step_number']}: {result['result']}\n"

        system_message = """You are an AI assistant capable of solving various types of problems.

Provide clear, specific, and actionable results. If the problem requires calculation, show your work. If it requires analysis, explain your reasoning."""

        user_message = f"{context}\nSolve this problem: {step.description}"
        
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=500
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"Error solving problem with LLM: {str(e)}"
    
    def _check_dependencies(self, step, completed_steps: List[Dict]) -> bool:
        if not step.dependencies:
            return True
            
        completed_step_numbers = {
            result["step_number"] for result in completed_steps 
            if result["success"]
        }
        
        return all(dep in completed_step_numbers for dep in step.dependencies)
    
    def _compile_final_result(self, step_results: List[Dict], goal: str) -> str:
        successful_results = [
            result for result in step_results 
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
        
        try:
            system_message = """You are summarizing search results to answer a user's question. 
Create a clear, concise answer that directly addresses what the user asked for.
Focus on the key facts and information. Do not mention steps, searches, or the process."""

            user_message = f"""Original question: {goal}

Search results and data:
{all_data}

Provide a direct, informative answer to the user's question."""
            
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=500
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            self.logger.error(f"Error creating summary: {e}")
            return f"Based on the search results: {all_data[:500]}..."
