"""Tests for per-user conversation memory across a restart.

Run with:  python -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import Memory, MemoryEntry


class _MemoryTestCase(unittest.TestCase):
    """Each test gets its own memory file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "agent_memory.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def restart(self):
        """Simulate a server restart by building a new Memory on the same file."""
        return Memory(memory_file=self.path)


class TestUserOwnership(_MemoryTestCase):

    def test_interaction_records_the_account_that_made_it(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q", "a", user_id="analyst")
        self.assertEqual(memory.short_term_memory[0].user_id, "analyst")

    def test_saved_session_keeps_user_ownership_on_disk(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q", "a", user_id="analyst")
        memory.end_current_session()

        with open(self.path, encoding="utf-8") as f:
            saved = json.load(f)
        interaction = saved["long_term"][0]["content"]["interactions"][0]
        self.assertEqual(interaction["user_id"], "analyst")

    def test_session_metadata_lists_the_users_involved(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q1", "a1", user_id="analyst")
        memory.add_interaction("q2", "a2", user_id="auditor")
        memory.end_current_session()
        self.assertEqual(
            memory.long_term_memory[0].metadata["users"], ["analyst", "auditor"]
        )

    def test_entry_without_a_user_id_defaults_rather_than_failing(self):
        # Memory files written before user_id existed must still load.
        entry = MemoryEntry(
            id="x", content={}, timestamp="2026-01-01T00:00:00", type="interaction"
        )
        self.assertEqual(entry.user_id, "default")


class TestRestoreAfterRestart(_MemoryTestCase):

    def test_history_is_restored_for_the_right_user(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("what is A.5.15", "access control", user_id="analyst")
        memory.end_current_session()

        restored = self.restart()
        history = restored.get_conversation_history(user_id="analyst")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["query"], "what is A.5.15")

    def test_restored_history_stays_separated_by_account(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("analyst question", "a", user_id="analyst")
        memory.add_interaction("auditor question", "a", user_id="auditor")
        memory.end_current_session()

        restored = self.restart()
        analyst = restored.get_conversation_history(user_id="analyst")
        auditor = restored.get_conversation_history(user_id="auditor")
        self.assertEqual([h["query"] for h in analyst], ["analyst question"])
        self.assertEqual([h["query"] for h in auditor], ["auditor question"])

    def test_unrelated_account_gets_no_history(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q", "a", user_id="analyst")
        memory.end_current_session()

        restored = self.restart()
        self.assertEqual(restored.get_conversation_history(user_id="auditor"), [])

    def test_history_survives_more_than_one_restart(self):
        first = Memory(memory_file=self.path)
        first.add_interaction("first", "a", user_id="analyst")
        first.end_current_session()

        second = self.restart()
        second.add_interaction("second", "a", user_id="analyst")
        second.end_current_session()

        third = self.restart()
        history = third.get_conversation_history(user_id="analyst")
        self.assertEqual([h["query"] for h in history], ["first", "second"])

    def test_restored_history_is_in_time_order(self):
        memory = Memory(memory_file=self.path)
        for i in range(3):
            memory.add_interaction(f"q{i}", "a", user_id="analyst")
        memory.end_current_session()

        restored = self.restart()
        history = restored.get_conversation_history(user_id="analyst", limit=10)
        self.assertEqual([h["query"] for h in history], ["q0", "q1", "q2"])

    def test_missing_memory_file_starts_empty(self):
        memory = Memory(memory_file=os.path.join(self.tmp, "absent.json"))
        self.assertEqual(memory.conversation_by_user, {})
        self.assertEqual(memory.get_conversation_history(user_id="analyst"), [])


if __name__ == "__main__":
    unittest.main()
