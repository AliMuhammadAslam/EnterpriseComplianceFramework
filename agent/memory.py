import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel
from utils.logger import logger_instance
from dotenv import load_dotenv

load_dotenv()


class MemoryEntry(BaseModel):
    id: str
    content: Dict[str, Any]
    timestamp: datetime
    type: str
    metadata: Optional[Dict[str, Any]] = None


class Memory:
    """Session memory for the agent.

    Short-term memory holds the current conversation in-process.
    Long-term memory persists completed sessions to a JSON file on disk
    so conversation history survives restarts.
    """

    def __init__(self, memory_file: str = None):
        self.logger = logger_instance.get_logger("memory")
        self.memory_file = memory_file or os.getenv("MEMORY_FILE", "agent_memory.json")
        self.short_term_memory: List[MemoryEntry] = []
        self.long_term_memory: List[MemoryEntry] = []
        self._load_persistent_memory()

    def add_interaction(self, query: str, response: str, metadata: Dict[str, Any] = None):
        """Append a query-response pair to short-term memory."""
        entry = MemoryEntry(
            id=f"interaction_{datetime.now().timestamp()}",
            content={"query": query, "response": response},
            timestamp=datetime.now(),
            type="interaction",
            metadata=metadata,
        )
        self.short_term_memory.append(entry)
        self.logger.info(f"Added interaction to memory: {query[:50]}...")

    def get_conversation_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return the most recent interactions from the current session."""
        recent = [e for e in self.short_term_memory if e.type == "interaction"][-limit:]
        return [e.content for e in recent]

    def start_new_session(self):
        """Persist the current session and start fresh."""
        if self.short_term_memory:
            self._save_current_session_to_long_term()
        self.short_term_memory.clear()
        self.logger.info("Started new session")

    def end_current_session(self):
        """Persist the current session to long-term memory."""
        if self.short_term_memory:
            self._save_current_session_to_long_term()
            self.short_term_memory.clear()
            self.logger.info("Session ended and saved to long-term memory")
        else:
            self.logger.info("No active session to end")

    def _save_current_session_to_long_term(self):
        if not self.short_term_memory:
            return

        session_entry = MemoryEntry(
            id=f"session_{datetime.now().timestamp()}",
            content={
                "interactions": [e.model_dump() for e in self.short_term_memory],
                "session_summary": f"Conversation with {len(self.short_term_memory)} interactions",
            },
            timestamp=datetime.now(),
            type="conversation_session",
            metadata={
                "interaction_count": len(self.short_term_memory),
                "start_time": self.short_term_memory[0].timestamp.isoformat(),
                "end_time": datetime.now().isoformat(),
            },
        )

        self.long_term_memory.append(session_entry)
        self._save_persistent_memory()
        self.logger.info(f"Saved session with {len(self.short_term_memory)} interactions")

    def _load_persistent_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r") as f:
                    data = json.load(f)
                self.long_term_memory = [
                    MemoryEntry(**entry) for entry in data.get("long_term", [])
                ]
                self.logger.info(f"Loaded {len(self.long_term_memory)} long-term memories")
            except Exception as e:
                self.logger.error(f"Failed to load memory file: {e}")

    def _save_persistent_memory(self):
        try:
            data = {"long_term": [e.model_dump() for e in self.long_term_memory]}
            with open(self.memory_file, "w") as f:
                json.dump(data, f, default=str, indent=2)
            self.logger.info("Saved persistent memory")
        except Exception as e:
            self.logger.error(f"Failed to save memory: {e}")
