import json
import os
import threading
import uuid
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
    # Defaults so memory files written before this field existed still load.
    user_id: str = "default"


class Memory:
    """Session memory for the agent.

    Short-term memory holds the current conversation in-process. Long-term
    memory persists completed sessions to a JSON file. Each interaction
    records the account it belongs to, and the per-user histories are rebuilt
    from that file on start, so follow-up context survives a restart.
    """

    def __init__(self, memory_file: str = None):
        self.logger = logger_instance.get_logger("memory")
        self.memory_file = memory_file or os.getenv("MEMORY_FILE", "agent_memory.json")
        self.short_term_memory: List[MemoryEntry] = []
        self.long_term_memory: List[MemoryEntry] = []
        # Per-user conversation history so follow-up questions stay scoped to
        # the user who asked them and don't leak across users.
        self.conversation_by_user: Dict[str, List[MemoryEntry]] = {}
        # Interactions each user has reset away. Saved, so a restart does not
        # bring back history the user asked to clear. Tracked by id rather
        # than by reset time: the clock can give a message sent just after a
        # reset the same timestamp as the reset itself.
        self.cleared_ids: Dict[str, List[str]] = {}
        # Requests run on parallel threads and every interaction is saved, so
        # changes and saves are serialised. Without it, concurrent saves
        # collided on the temporary file and most of them failed.
        self._lock = threading.RLock()
        self._load_persistent_memory()

    def add_interaction(
        self,
        query: str,
        response: str,
        user_id: str = "default",
        metadata: Dict[str, Any] = None,
    ):
        """Append a query-response pair to short-term and per-user memory."""
        entry = MemoryEntry(
            # Unique even for two interactions within one clock tick.
            id=f"interaction_{uuid.uuid4().hex}",
            content={"query": query, "response": response},
            timestamp=datetime.now(),
            type="interaction",
            metadata=metadata,
            user_id=user_id,
        )
        with self._lock:
            self.short_term_memory.append(entry)
            self.conversation_by_user.setdefault(user_id, []).append(entry)
            # Saved straight away. Holding the session in memory until
            # shutdown lost every conversation since start-up on a crash.
            self._save_persistent_memory()
        self.logger.info(f"Added interaction to memory: {query[:50]}...")

    def get_conversation_history(
        self, user_id: str = "default", limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Return the most recent interactions for a specific user."""
        entries = self.conversation_by_user.get(user_id, [])
        recent = [e for e in entries if e.type == "interaction"][-limit:]
        return [e.content for e in recent]

    def clear_user_conversation(self, user_id: str = "default"):
        """Clear only this user's follow-up conversation history.

        Scoped to one user so resetting one person's session doesn't wipe
        everyone else's conversation context. The cleared interactions are
        recorded and skipped when history is rebuilt, so the reset holds
        across a restart; the interactions themselves are kept on disk.
        """
        with self._lock:
            cleared = self.conversation_by_user.pop(user_id, [])
            ids = set(self.cleared_ids.get(user_id, []))
            ids.update(entry.id for entry in cleared)
            self.cleared_ids[user_id] = sorted(ids)
            self._save_persistent_memory()
        self.logger.info(f"Cleared conversation history for user: {user_id}")

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
        with self._lock:
            self._close_session_locked()

    def _close_session_locked(self):
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
                "users": sorted({e.user_id for e in self.short_term_memory}),
            },
        )

        count = len(self.short_term_memory)
        self.long_term_memory.append(session_entry)
        # Cleared before saving, or the file would hold these interactions
        # both in the session and as an unfinished one, restored twice.
        self.short_term_memory = []
        self._save_persistent_memory()
        self.logger.info(f"Saved session with {count} interactions")

    def _load_persistent_memory(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.long_term_memory = [
                    MemoryEntry(**entry) for entry in data.get("long_term", [])
                ]
                self.cleared_ids = dict(data.get("cleared_ids", {}))
                # Interactions saved during a session that never ended
                # cleanly. Kept as a session of their own so they are restored.
                self.short_term_memory = [
                    MemoryEntry(**entry) for entry in data.get("current_session", [])
                ]
                if self.short_term_memory:
                    self._save_current_session_to_long_term()
                self._rebuild_user_conversations()
                self.logger.info(
                    f"Loaded {len(self.long_term_memory)} long-term memories, "
                    f"restored history for {len(self.conversation_by_user)} user(s)"
                )
            except Exception as e:
                self.logger.error(f"Failed to load memory file: {e}")

    def _rebuild_user_conversations(self):
        """Rebuild each account's history from the saved sessions.

        Without this the per-user history starts empty after a restart and a
        follow-up question loses the exchange it refers to.
        """
        restored: Dict[str, List[MemoryEntry]] = {}
        cleared = {user: set(ids) for user, ids in self.cleared_ids.items()}

        for session in self.long_term_memory:
            if session.type != "conversation_session":
                continue
            for raw in session.content.get("interactions", []):
                try:
                    entry = MemoryEntry(**raw)
                except Exception as e:
                    self.logger.warning(f"Skipped an unreadable interaction: {e}")
                    continue
                if entry.type != "interaction":
                    continue
                if entry.id in cleared.get(entry.user_id, ()):
                    continue
                restored.setdefault(entry.user_id, []).append(entry)

        for entries in restored.values():
            entries.sort(key=lambda e: e.timestamp)

        self.conversation_by_user = restored

    def _save_persistent_memory(self):
        with self._lock:
            self._write_file_locked()

    def _write_file_locked(self):
        tmp_path = f"{self.memory_file}.tmp"
        try:
            data = {
                "long_term": [e.model_dump() for e in self.long_term_memory],
                "current_session": [e.model_dump() for e in self.short_term_memory],
                "cleared_ids": self.cleared_ids,
            }
            # Write then swap, so an interrupted save cannot truncate the file.
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, default=str, indent=2)
            os.replace(tmp_path, self.memory_file)
            self.logger.info("Saved persistent memory")
        except Exception as e:
            self.logger.error(f"Failed to save memory: {e}")
