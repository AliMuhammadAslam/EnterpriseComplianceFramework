from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel
from utils.logger import logger_instance

class ToolInput(BaseModel):
    pass

class ToolOutput(BaseModel):
    success: bool
    result: Any
    error: Optional[str] = None

class BaseTool(ABC):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.logger = logger_instance.get_logger(f"tool.{name}")
        
    @abstractmethod
    def _execute(self, input_data: ToolInput) -> Any:
        pass
    
    @abstractmethod
    def get_input_schema(self) -> Dict[str, Any]:
        pass
    
    def execute(self, input_data: Dict[str, Any]) -> ToolOutput:
        try:
            self.logger.info(f"Executing tool with input: {input_data}")
            
            validated_input = self._validate_input(input_data)
            result = self._execute(validated_input)
            
            output = ToolOutput(success=True, result=result)
            self.logger.info(f"Tool execution successful: {result}")
            return output
            
        except Exception as e:
            error_msg = f"Tool execution failed: {str(e)}"
            self.logger.error(error_msg)
            return ToolOutput(success=False, result=None, error=error_msg)
    
    def _validate_input(self, input_data: Dict[str, Any]) -> ToolInput:
        return ToolInput(**input_data)
    
    def get_metadata(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_input_schema()
        }