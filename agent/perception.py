from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
import os
from typing import Dict, Any, Optional
from utils.logger import logger_instance

class PerceptionInput(BaseModel):
    content: str
    source: str = "user"
    metadata: Optional[Dict[str, Any]] = None

class PerceptionOutput(BaseModel):
    structured_input: Dict[str, Any]
    intent: str
    context: Dict[str, Any]

class Perception:
    def __init__(self):
        self.logger = logger_instance.get_logger("perception")
        load_dotenv()
        self.model_config = {
            "model": f"openai/{os.getenv('DEFAULT_MODEL', 'gpt-4o')}",
            "temperature": float(os.getenv('TEMPERATURE', '0.3')),
            "max_tokens": int(os.getenv('MAX_TOKENS', '100'))
        }
        
    def process_input(self, raw_input: str, source: str = "user") -> PerceptionOutput:
        try:
            self.logger.info(f"Processing input from {source}: {raw_input[:100]}...")
            
            perception_input = PerceptionInput(
                content=raw_input,
                source=source
            )
            
            intent = self._detect_intent(perception_input.content)
            context = self._extract_context(perception_input.content)
            
            structured_input = {
                "original_content": perception_input.content,
                "source": perception_input.source,
                "metadata": perception_input.metadata or {}
            }
            
            output = PerceptionOutput(
                structured_input=structured_input,
                intent=intent,
                context=context
            )
            
            self.logger.info(f"Input processed. Intent: {intent}")
            return output
            
        except Exception as e:
            self.logger.error(f"Error processing input: {e}")
            raise
    
    def _detect_intent(self, content: str) -> str:
        try:
            system_message = """Classify the user's request into one of these categories:

- problem_solving: Requires reasoning, analysis, or solving problems
- information_seeking: Requests for facts, definitions, or research  
- planning: Requests for step-by-step procedures or plans
- general_query: Casual conversation or greetings

Respond with only the category name."""

            user_message = f"Classify this request: {content}"
            
            response = completion(
                model=self.model_config["model"],
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,
                max_tokens=20
            )
            
            intent = response.choices[0].message.content.strip().lower()
            
            # Validate the response is one of our expected intents
            valid_intents = ["problem_solving", "information_seeking", "planning", "general_query"]
            if intent in valid_intents:
                return intent
            else:
                return self._fallback_intent_detection(content)
                
        except Exception as e:
            self.logger.error(f"Error in LLM intent detection: {e}")
            return self._fallback_intent_detection(content)
    
    def _fallback_intent_detection(self, content: str) -> str:
        content_lower = content.lower()
        
        if any(word in content_lower for word in ["search", "find", "what is", "who is", "define"]):
            return "information_seeking"
        elif any(word in content_lower for word in ["plan", "steps", "how to", "procedure"]):
            return "planning"
        elif any(word in content_lower for word in ["how", "solve", "fix", "calculate", "determine", "figure out"]):
            return "problem_solving"
        else:
            return "general_query"
    
    def _extract_context(self, content: str) -> Dict[str, Any]:
        return {
            "length": len(content),
            "word_count": len(content.split()),
            "has_numbers": any(char.isdigit() for char in content),
            "has_questions": "?" in content
        }