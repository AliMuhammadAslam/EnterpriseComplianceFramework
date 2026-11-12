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


class TestDurability(_MemoryTestCase):

    def test_interaction_survives_a_crash_before_shutdown(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("asked before the crash", "a", user_id="analyst")
        # No end_current_session: the process died.

        restored = self.restart()
        history = restored.get_conversation_history(user_id="analyst")
        self.assertEqual([h["query"] for h in history], ["asked before the crash"])

    def test_recovered_session_is_not_duplicated_on_later_restarts(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q", "a", user_id="analyst")
        self.restart()
        third = self.restart()
        self.assertEqual(len(third.get_conversation_history(user_id="analyst")), 1)

    def test_clean_shutdown_does_not_duplicate_history(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q", "a", user_id="analyst")
        memory.end_current_session()
        restored = self.restart()
        self.assertEqual(len(restored.get_conversation_history(user_id="analyst")), 1)


class TestConcurrentSaves(_MemoryTestCase):

    def test_parallel_chats_never_fail_a_save_or_lose_an_interaction(self):
        import threading
        from unittest import mock

        memory = Memory(memory_file=self.path)

        def chat(user):
            for i in range(25):
                memory.add_interaction(f"{user} q{i}", "a" * 1000, user_id=user)

        with mock.patch.object(memory.logger, "error") as logged_error:
            threads = [threading.Thread(target=chat, args=(f"u{n}",)) for n in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        logged_error.assert_not_called()

        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["current_session"]), 125)


class TestReset(_MemoryTestCase):

    def test_reset_holds_across_a_restart(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("before reset", "a", user_id="analyst")
        memory.end_current_session()
        memory.clear_user_conversation("analyst")

        restored = self.restart()
        self.assertEqual(restored.get_conversation_history(user_id="analyst"), [])

    def test_history_after_a_reset_is_kept(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("before reset", "a", user_id="analyst")
        memory.clear_user_conversation("analyst")
        memory.add_interaction("after reset", "a", user_id="analyst")

        restored = self.restart()
        history = restored.get_conversation_history(user_id="analyst")
        self.assertEqual([h["query"] for h in history], ["after reset"])

    def test_message_in_the_same_clock_tick_as_the_reset_is_kept(self):
        # Windows' clock can give a reset and the next message one timestamp.
        from datetime import datetime as real_datetime
        from unittest import mock

        frozen = real_datetime(2026, 11, 4, 12, 0, 0)

        class FrozenClock(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

        with mock.patch("agent.memory.datetime", FrozenClock):
            memory = Memory(memory_file=self.path)
            memory.add_interaction("before reset", "a", user_id="analyst")
            memory.clear_user_conversation("analyst")
            memory.add_interaction("same tick, after reset", "a", user_id="analyst")
            restored = self.restart()

        history = restored.get_conversation_history(user_id="analyst")
        self.assertEqual([h["query"] for h in history], ["same tick, after reset"])

    def test_reset_leaves_other_users_alone(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("analyst q", "a", user_id="analyst")
        memory.add_interaction("auditor q", "a", user_id="auditor")
        memory.clear_user_conversation("analyst")

        self.assertEqual(len(memory.get_conversation_history(user_id="auditor")), 1)
        restored = self.restart()
        self.assertEqual(len(restored.get_conversation_history(user_id="auditor")), 1)
        self.assertEqual(restored.get_conversation_history(user_id="analyst"), [])


class TestRecentInteractions(_MemoryTestCase):
    """What the web page redisplays after a reload."""

    def test_returns_this_users_exchanges_oldest_first_with_times(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("q1", "a1", user_id="analyst")
        memory.add_interaction("other", "x", user_id="auditor")
        memory.add_interaction("q2", "a2", user_id="analyst")
        history = memory.get_recent_interactions("analyst")
        self.assertEqual([h["query"] for h in history], ["q1", "q2"])
        self.assertEqual([h["response"] for h in history], ["a1", "a2"])
        self.assertTrue(all(h["timestamp"] for h in history))

    def test_limit_keeps_the_latest(self):
        memory = Memory(memory_file=self.path)
        for i in range(5):
            memory.add_interaction(f"q{i}", f"a{i}", user_id="analyst")
        history = memory.get_recent_interactions("analyst", limit=2)
        self.assertEqual([h["query"] for h in history], ["q3", "q4"])

    def test_reset_conversation_is_not_returned_even_after_a_restart(self):
        memory = Memory(memory_file=self.path)
        memory.add_interaction("old", "a", user_id="analyst")
        memory.clear_user_conversation("analyst")
        memory.add_interaction("new", "b", user_id="analyst")
        self.assertEqual(
            [h["query"] for h in memory.get_recent_interactions("analyst")], ["new"]
        )
        self.assertEqual(
            [h["query"] for h in self.restart().get_recent_interactions("analyst")], ["new"]
        )

    def test_unknown_user_gets_nothing(self):
        memory = Memory(memory_file=self.path)
        self.assertEqual(memory.get_recent_interactions("nobody"), [])


if __name__ == "__main__":
    unittest.main()
