from typing import Dict, Any, Callable, List
from dataclasses import dataclass
from enum import Enum

class MessageType(Enum):
    TOOL_EXECUTED = "tool_executed"
    ERROR_OCCURRED = "error_occurred"
    PLAN_GENERATED = "plan_generated"
    STEP_EXECUTED = "step_executed"

@dataclass
class Message:
    type: MessageType
    sender: str
    data: Dict[str, Any]
    timestamp: float = None
    
    def __post_init__(self):
        if self.timestamp is None:
            import time
            self.timestamp = time.time()

class CommunicationBus:
    def __init__(self):
        self._message_history: List[Message] = []
        
    def publish(self, message: Message):
        self._message_history.append(message)
                    
    def clear_history(self):
        self._message_history.clear()

bus = CommunicationBus()
