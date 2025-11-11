from typing import Dict, Any, List, Tuple
from litellm import completion
from utils.logger import logger_instance
import os
from dotenv import load_dotenv

load_dotenv()

class ReasoningEngine:
    def __init__(self, tool_manager=None):
        self.tool_manager = tool_manager
        self.logger = logger_instance.get_logger("reasoning")
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": float(os.getenv('TEMPERATURE', '0.7')),
            "max_tokens": int(os.getenv('MAX_TOKENS', '2000'))
        }
        self.reasoning_config = {
            "max_iterations": int(os.getenv('MAX_ITERATIONS', '5')),
            "strategy_threshold": 10
        }
        
    def select_strategy(self, perception_output) -> str:
        content = perception_output.structured_input["original_content"]
        intent = perception_output.intent
        
        try:
            system_message = """Choose the best strategy for this request:

- react: Simple tasks solved through iterative reasoning
- plan_and_execute: Complex tasks requiring structured planning

Consider if the task needs multiple coordinated steps or can be solved directly.

Respond with only: react OR plan_and_execute"""

            user_message = f"Content: {content}\nIntent: {intent}\nRecommend strategy:"
            
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,
                max_tokens=20
            )
            
            strategy = response.choices[0].message.content.strip().lower()
            
            # Validate the response
            if strategy in ["react", "plan_and_execute"]:
                self.logger.info(f"Selected strategy: {strategy} (intent: {intent}, LLM decision)")
                return strategy
            else:
                return self._fallback_strategy_selection(intent)
                
        except Exception as e:
            self.logger.error(f"Error in LLM strategy selection: {e}")
            return self._fallback_strategy_selection(intent)
    
    def _fallback_strategy_selection(self, intent: str) -> str:
        if intent in ["planning"]:
            strategy = "plan_and_execute"
        else:
            strategy = "react"
        
        self.logger.info(f"Selected strategy: {strategy} (intent: {intent}, fallback)")
        return strategy
    
    def react_loop(self, perception_output, memory, verbose: bool = False) -> tuple:
        prompt = perception_output.structured_input["original_content"]
        conversation_history = memory.get_conversation_history()
        
        # Search for relevant context from previous sessions
        relevant_history = memory.search_relevant_memory(prompt, limit=3)

        context = self._build_context(conversation_history, relevant_history)
        iterations_completed = 0

        for iteration in range(self.reasoning_config["max_iterations"]):
            iterations_completed = iteration + 1
            if verbose:
                print(f"[REASONING] ReAct iteration {iteration + 1}/"
                      f"{self.reasoning_config['max_iterations']}")

            self.logger.info(f"ReAct iteration {iteration + 1}")

            thought = self._generate_thought(prompt, context)
            
            if verbose:
                print(f"[REASONING] Thought: {thought}")
            
            self.logger.info(f"Thought: {thought}")
            
            action_decision = self._decide_action(thought, prompt)
            
            if verbose:
                print(f"[REASONING] Action decision: {action_decision.get('action', 'unknown')}")
            
            if action_decision["action"] == "final_answer":
                if verbose:
                    print(f"[REASONING] Providing final answer")
                return action_decision["content"], iterations_completed
            
            if action_decision["action"] == "use_tool":
                if verbose:
                    print(f"[REASONING] Using tool: {action_decision.get('tool_name', 'unknown')}")
                
                tool_result = self._execute_tool_action(action_decision)
                observation = f"Tool result: {tool_result}"
                
                if verbose:
                    print(f"[REASONING] Tool result: {str(tool_result)[:100]}...")
                
                context += f"\nObservation: {observation}"
                prompt += f"\nObservation: {observation}"
            else:
                observation = "No tool needed for this step."
                context += f"\nObservation: {observation}"
            
            if self._is_finished(prompt, context):
                if verbose:
                    print(f"[REASONING] Loop finished early")
                break
                
        final_answer = self._generate_final_answer(prompt, context)
        
        if verbose:
            print(f"[REASONING] Generated final answer")
        
        return final_answer, iterations_completed
    
    def _generate_thought(self, prompt: str, context: str) -> str:
        system_message = """You are an AI agent's reasoning component. Generate a clear thought about what you need to do next to answer the user's query. Be concise and specific."""
        
        user_message = f"Context: {context}\nUser Query: {prompt}\nWhat should I think about next?"
        
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.7,
                max_tokens=200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            self.logger.error(f"Error generating thought: {e}")
            return "I need to analyze this query and determine the best approach."
    
    def _decide_action(self, thought: str, prompt: str) -> Dict[str, Any]:
        import re
        math_patterns = [
            r'\d+\s*[\+\-\*/\^]\s*\d+',
            r'calculate|compute|solve|what is.*\d+.*[\+\-\*/\^].*\d+',
            r'what.*is.*\d+.*[\+\-\*/\^].*\d+',
            r'\d+\s*(plus|minus|times|divided by|multiplied by|to the power of)\s*\d+',
            r'square root of \d+',
            r'\d+\s*squared',
        ]
        
        prompt_lower = prompt.lower()
        for pattern in math_patterns:
            if re.search(pattern, prompt_lower):
                math_expression = self._extract_math_expression(prompt)
                return {
                    "action": "use_tool",
                    "tool_name": "calculator", 
                    "tool_input": {"expression": math_expression}
                }
        
        available_tools = ""
        if self.tool_manager:
            available_tools = self.tool_manager.get_tools_description()
        
        system_message = f"""You are an AI agent deciding what action to take. You can either:
1. Use a tool (respond with tool name and input)
2. Give a final answer

Available tools:
{available_tools}

For mathematical calculations, ALWAYS use the calculator tool instead of solving directly.

Respond in JSON format:
{{"action": "use_tool" or "final_answer", "tool_name": "tool_name", "tool_input": {{}}, "content": "final answer or reasoning"}}"""

        user_message = f"Thought: {thought}\nUser Query: {prompt}\nWhat action should I take?"
        
        try:
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.3,
                max_tokens=300
            )
            
            content = response.choices[0].message.content.strip()
            
            import json
            try:
                return json.loads(content)
            except:
                if "calculator" in content.lower() and any(char in content for char in "+-*/"):
                    return {
                        "action": "use_tool",
                        "tool_name": "calculator",
                        "tool_input": {"expression": self._extract_math_expression(content)}
                    }
                elif "search" in content.lower() or "find" in content.lower():
                    return {
                        "action": "use_tool", 
                        "tool_name": "web_search",
                        "tool_input": {"query": prompt}
                    }
                else:
                    return {"action": "final_answer", "content": content}
                    
        except Exception as e:
            self.logger.error(f"Error deciding action: {e}")
            return {"action": "final_answer", "content": "I encountered an error while processing your request."}
    
    def _execute_tool_action(self, action_decision: Dict[str, Any]) -> str:
        if not self.tool_manager:
            return "Tool manager not available"
            
        tool_name = action_decision.get("tool_name")
        tool_input = action_decision.get("tool_input", {})
        
        result = self.tool_manager.execute_tool(tool_name, tool_input)
        
        if result.success:
            return str(result.result)
        else:
            return f"Tool error: {result.error}"
    
    def _is_finished(self, prompt: str, context: str) -> bool:
        return "final answer" in context.lower() or len(context) > 2000
    
    def _generate_final_answer(self, prompt: str, context: str) -> str:
        system_message = """You are an AI agent providing a final answer. Based on the context and reasoning, provide a clear, helpful response to the user's query."""
        
        user_message = f"Context: {context}\nUser Query: {prompt}\nProvide your final answer:"
        
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
            self.logger.error(f"Error generating final answer: {e}")
            return "I apologize, but I encountered an error while generating the final answer."
    
    def _build_context(self, conversation_history: List[Dict[str, Any]],
                       relevant_history: List[Dict[str, Any]] = None) -> str:
        context_parts = []

        if relevant_history:
            context_parts.append("Relevant context from previous conversations:")
            for i, entry in enumerate(relevant_history[:2], 1):
                context_parts.append(f"Past Q{i}: {entry['query']}")
                response_text = entry['response']
                if len(response_text) > 200:
                    response_text = response_text[:200] + '...'
                context_parts.append(f"Past A{i}: {response_text}")
            context_parts.append("")

        if conversation_history:
            context_parts.append("Current session conversation:")
            for entry in conversation_history[-3:]:
                context_parts.append(f"Q: {entry['query']}")
                context_parts.append(f"A: {entry['response']}")
        else:
            context_parts.append("No current conversation history.")

        return "\n".join(context_parts)
    
    def _extract_math_expression(self, text: str) -> str:
        import re
        
        text = text.lower()
        text = re.sub(r'\bplus\b', '+', text)
        text = re.sub(r'\bminus\b', '-', text)
        text = re.sub(r'\btimes\b|\bmultiplied by\b', '*', text)
        text = re.sub(r'\bdivided by\b', '/', text)
        
        math_patterns = [
            r'\d+(?:\.\d+)?\s*[\+\-\*/]\s*\d+(?:\.\d+)?(?:\s*[\+\-\*/]\s*\d+(?:\.\d+)?)*',
            r'\d+(?:\.\d+)?\s*[\+\-\*/]\s*\d+(?:\.\d+)?',
        ]
        
        for pattern in math_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if any(op in match for op in "+-*/"):
                    return match.strip()
        
        numbers = re.findall(r'\d+(?:\.\d+)?', text)
        if len(numbers) >= 2:
            operators = re.findall(r'[\+\-\*/]', text)
            if operators:
                return f"{numbers[0]} {operators[0]} {numbers[1]}"
            else:
                return f"{numbers[0]} + {numbers[1]}"
        
        return text