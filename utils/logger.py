import logging
import sys
from typing import Optional

class AgentLogger:
    _instance: Optional['AgentLogger'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self.logger = logging.getLogger("ai_agent")
        self.logger.setLevel(logging.INFO)  # Default to INFO level
        
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            
        self._initialized = True
    
    def get_logger(self, component_name: str) -> logging.Logger:
        return logging.getLogger(f"ai_agent.{component_name}")

logger_instance = AgentLogger()