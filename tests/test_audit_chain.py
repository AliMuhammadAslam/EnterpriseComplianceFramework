"""Tests for audit log hash chaining and concurrent writing.

Run with:  python -m unittest discover -s tests
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_logger import AuditLogger, GENESIS_HASH, compute_entry_hash


class _ChainTestCase(unittest.TestCase):
    """Gives each test its own log directory and a fresh singleton."""

    def setUp(self):
        AuditLogger._reset_singleton()
        self.tmp = tempfile.mkdtemp()
        self.audit = AuditLogger(log_dir=self.tmp)

    def tearDown(self):
        AuditLogger._reset_singleton()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read_lines(self):
        with open(self.audit.log_file, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class TestChaining(_ChainTestCase):

    def test_first_entry_links_to_genesis(self):
        self.audit.log("LOGIN", user_id="john")
        entry = self.read_lines()[0]
        self.assertEqual(entry["prev_hash"], GENESIS_HASH)
        self.assertTrue(entry["entry_hash"])

    def test_each_entry_links_to_its_predecessor(self):
        for action in ("LOGIN", "CHAT_QUERY", "EVALUATION_RUN"):
            self.audit.log(action, user_id="john")
        entries = self.read_lines()
        for earlier, later in zip(entries, entries[1:]):
            self.assertEqual(later["prev_hash"], earlier["entry_hash"])

    def test_hash_covers_entry_contents(self):
        self.audit.log("LOGIN", user_id="john")
        entry = self.read_lines()[0]
        self.assertEqual(compute_entry_hash(entry), entry["entry_hash"])

    def test_chain_head_survives_restart(self):
        self.audit.log("LOGIN", user_id="john")
        head = self.read_lines()[-1]["entry_hash"]

        AuditLogger._reset_singleton()
        reopened = AuditLogger(log_dir=self.tmp)
        reopened.log("LOGOUT", user_id="john")

        self.assertEqual(self.read_lines()[-1]["prev_hash"], head)


class TestVerification(_ChainTestCase):

    def test_untouched_log_verifies(self):
        for action in ("LOGIN", "DOCUMENT_UPLOAD", "EVALUATION_RUN"):
            self.audit.log(action, user_id="john")
        result = self.audit.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["verified"], 3)
        self.assertEqual(result["problems"], [])

    def test_edited_entry_is_detected(self):
        self.audit.log("LOGIN", user_id="john")
        self.audit.log("EVALUATION_RUN", user_id="john")
        self.audit.log("LOGOUT", user_id="john")

        # Tamper: change who performed the middle action.
        entries = self.read_lines()
        entries[1]["user_id"] = "attacker"
        with open(self.audit.log_file, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        result = self.audit.verify_chain()
        self.assertFalse(result["intact"])
        self.assertIn("do not match", result["problems"][0]["problem"])

    def test_deleted_entry_is_detected(self):
        self.audit.log("LOGIN", user_id="john")
        self.audit.log("EVALUATION_RUN", user_id="john")
        self.audit.log("LOGOUT", user_id="john")

        # Tamper: remove the middle entry entirely.
        entries = self.read_lines()
        del entries[1]
        with open(self.audit.log_file, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        result = self.audit.verify_chain()
        self.assertFalse(result["intact"])
        self.assertIn("predecessor link", result["problems"][0]["problem"])

    def test_legacy_unchained_entries_are_not_failures(self):
        # An entry written before hash chaining existed.
        with open(self.audit.log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "event_id": "old123",
                "timestamp": "2026-01-01T00:00:00",
                "user_id": "john",
                "action": "LOGIN",
            }) + "\n")

        AuditLogger._reset_singleton()
        audit = AuditLogger(log_dir=self.tmp)
        audit.log("LOGOUT", user_id="john")

        result = audit.verify_chain()
        self.assertTrue(result["intact"])
        self.assertEqual(result["unchained_legacy_entries"], 1)
        self.assertEqual(result["verified"], 1)


class TestConcurrency(_ChainTestCase):

    def test_concurrent_writes_produce_an_unbroken_chain(self):
        # Without the lock, two threads can chain from the same predecessor.
        def write(n):
            for i in range(20):
                self.audit.log("CHAT_QUERY", user_id=f"user{n}", resource_id=str(i))

        threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = self.audit.verify_chain()
        self.assertEqual(result["total_entries"], 80)
        self.assertTrue(result["intact"], f"chain broken: {result['problems'][:3]}")

    def test_no_lines_are_lost_or_corrupted(self):
        def write(n):
            for i in range(25):
                self.audit.log("CHAT_QUERY", user_id=f"user{n}")

        threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every line must be valid JSON, and none may be interleaved.
        self.assertEqual(len(self.read_lines()), 100)


if __name__ == "__main__":
    unittest.main()
