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
    def __init__(self, memory_file: str = None):
        self.logger = logger_instance.get_logger("memory")
        self.memory_file = memory_file or os.getenv(
            'MEMORY_FILE', 'agent_memory.json'
        )
        self.short_term_memory: List[MemoryEntry] = []
        self.long_term_memory: List[MemoryEntry] = []
        self._load_persistent_memory()
        
    def add_interaction(self, query: str, response: str,
                        metadata: Dict[str, Any] = None):
        entry = MemoryEntry(
            id=f"interaction_{datetime.now().timestamp()}",
            content={"query": query, "response": response},
            timestamp=datetime.now(),
            type="interaction",
            metadata=metadata
        )

        self.short_term_memory.append(entry)
        self.logger.info(f"Added interaction to memory: {query[:50]}...")
    
    def get_conversation_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        recent_interactions = [
            entry for entry in self.short_term_memory
            if entry.type == "interaction"
        ][-limit:]

        return [entry.content for entry in recent_interactions]
    
    def search_relevant_memory(self, query: str,
                               limit: int = 5) -> List[Dict[str, Any]]:
        if not self.long_term_memory:
            return []

        relevant_interactions = []
        query_lower = query.lower()

        for session in self.long_term_memory:
            if session.type == "conversation_session":
                interactions = session.content.get("interactions", [])
                for interaction in interactions:
                    content = interaction.get("content", {})
                    user_query = content.get("query", "").lower()
                    agent_response = content.get("response", "").lower()

                    if (query_lower in user_query or
                        query_lower in agent_response or
                        any(word in user_query or word in agent_response
                            for word in query_lower.split()
                            if len(word) > 3)):

                        relevant_interactions.append({
                            "query": content.get("query", ""),
                            "response": content.get("response", ""),
                            "timestamp": interaction.get("timestamp", ""),
                            "session_id": session.id
                        })

        def relevance_score(interaction):
            score = 0
            content_text = (f"{interaction['query']} "
                            f"{interaction['response']}").lower()
            for word in query_lower.split():
                if len(word) > 3:
                    score += content_text.count(word.lower())
            return score

        relevant_interactions.sort(key=relevance_score, reverse=True)
        return relevant_interactions[:limit]
    
    def start_new_session(self):
        if self.short_term_memory:
            self._save_current_session_to_long_term()
        self.short_term_memory.clear()
        self.logger.info("Started new chat session")
    
    def end_current_session(self):
        if self.short_term_memory:
            self._save_current_session_to_long_term()
            self.short_term_memory.clear()
            self.logger.info("Ended current session and saved to "
                             "long-term memory")
        else:
            self.logger.info("No active session to end")
    
    def _save_current_session_to_long_term(self):
        if not self.short_term_memory:
            return

        session_entry = MemoryEntry(
            id=f"session_{datetime.now().timestamp()}",
            content={
                "interactions": [entry.dict()
                                 for entry in self.short_term_memory],
                "session_summary": (f"Conversation with "
                                    f"{len(self.short_term_memory)} "
                                    f"interactions")
            },
            timestamp=datetime.now(),
            type="conversation_session",
            metadata={
                "interaction_count": len(self.short_term_memory),
                "start_time": (self.short_term_memory[0].timestamp
                               .isoformat()
                               if self.short_term_memory else None),
                "end_time": datetime.now().isoformat()
            }
        )

        self.long_term_memory.append(session_entry)
        self._save_persistent_memory()
        self.logger.info(f"Saved session with {len(self.short_term_memory)} "
                         f"interactions to long-term memory")
    
    def _load_persistent_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r') as f:
                    data = json.load(f)
                    self.long_term_memory = [
                        MemoryEntry(**entry)
                        for entry in data.get('long_term', [])
                    ]
                self.logger.info(f"Loaded {len(self.long_term_memory)} "
                                 f"long-term memories")
            except Exception as e:
                self.logger.error(f"Failed to load memory file: {e}")
    
    def _save_persistent_memory(self):
        try:
            data = {
                'long_term': [entry.dict() for entry in self.long_term_memory]
            }
            with open(self.memory_file, 'w') as f:
                json.dump(data, f, default=str, indent=2)
            self.logger.info("Saved persistent memory")
        except Exception as e:
            self.logger.error(f"Failed to save memory: {e}")
    
    def clear_short_term(self):
        self.short_term_memory.clear()
        self.logger.info("Cleared short-term memory")