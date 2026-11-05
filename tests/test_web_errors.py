"""Tests that the web app does not hand internal error text to the browser,
and rejects oversized requests before reading them.

Builds the real Flask app against throwaway folders; the model is stubbed.

Run with:  python -m unittest discover -s tests
"""

import atexit
import contextlib
import io
import os
import shutil
import signal
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

LEAK = "Incorrect API key provided: sk-inval*****1234"


class _WebAppCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        env = {
            "SECRET_KEY": "test-only", "OPENAI_API_KEY": "sk-test-not-used",
            "USERS_FILE": os.path.join(cls.tmp, "users.json"),
            "REPORTS_DIR": os.path.join(cls.tmp, "reports"),
            "UPLOAD_DIR": os.path.join(cls.tmp, "uploads"),
            "AUDIT_LOG_DIR": os.path.join(cls.tmp, "audit"),
            "EVIDENCE_TRACE_DIR": os.path.join(cls.tmp, "traces"),
            "MEMORY_FILE": os.path.join(cls.tmp, "memory.json"),
            "CHROMA_DB_PATH": os.path.join(cls.tmp, "chroma"),
            "KNOWLEDGE_BASE_PATH": os.path.join(cls.tmp, "kb"),
            "MAX_UPLOAD_SIZE_MB": "1",
        }
        os.makedirs(env["KNOWLEDGE_BASE_PATH"])
        cls.env = mock.patch.dict(os.environ, env)
        cls.env.start()
        from audit.audit_logger import AuditLogger
        AuditLogger._reset_singleton()
        sys.modules.pop("web_app", None)
        # Importing the app installs signal handlers and an exit hook that
        # writes to the audit folder; both are undone in tearDownClass.
        cls.saved_signals = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        with contextlib.redirect_stdout(io.StringIO()):
            import web_app
        cls.web_app = web_app

    @classmethod
    def tearDownClass(cls):
        atexit.unregister(cls.web_app.cleanup_session)
        for sig, handler in cls.saved_signals.items():
            signal.signal(sig, handler)
        cls.env.stop()
        sys.modules.pop("web_app", None)
        from audit.audit_logger import AuditLogger
        AuditLogger._reset_singleton()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.client = self.web_app.app.test_client()
        with self.client.session_transaction() as s:
            s["user_id"] = "default"


class TestErrorText(_WebAppCase):

    def test_unexpected_failure_returns_a_reference_not_the_exception(self):
        with mock.patch.object(self.web_app.report_store, "list_reports",
                               side_effect=RuntimeError(LEAK)):
            r = self.client.get("/reports")
        self.assertEqual(r.status_code, 500)
        error = r.get_json()["error"]
        self.assertNotIn("sk-inval", error)
        self.assertIn("reference", error)

    def test_failed_evaluation_does_not_expose_the_provider_error(self):
        orch = self.web_app.orchestrator
        with mock.patch.object(orch.upload_manager, "get_user_doc_count", return_value=1), \
             mock.patch.object(orch, "evaluate_compliance_traced", side_effect=RuntimeError(LEAK)):
            r = self.client.post("/evaluate", json={"standards": ["GDPR"]})
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("sk-inval", r.get_json()["error"])

    def test_partial_chat_failure_keeps_the_answer_but_not_the_detail(self):
        from agent.orchestrator import OrchestrationResult
        result = OrchestrationResult(success=False, result="partial answer",
                                     strategy_used="plan_and_execute", error=f"Step 2 failed: {LEAK}")
        with mock.patch.object(self.web_app.orchestrator, "run", return_value=result):
            r = self.client.post("/chat", json={"message": "q"})
        body = r.get_json()
        self.assertEqual(body["response"], "partial answer")
        self.assertNotIn("sk-inval", body["error"])
        self.assertIn("reference", body["error"])

    def test_validation_messages_written_by_the_app_still_reach_the_user(self):
        r = self.client.post("/upload", data={"file": (io.BytesIO(b"x"), "notes.exe")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unsupported file type", r.get_json()["error"])


class TestBadInput(_WebAppCase):

    def test_audit_paging_rejects_non_numbers_and_negatives(self):
        for query in ("limit=abc", "offset=x", "limit=-5", "limit=0", "offset=-3", "limit=100000"):
            r = self.client.get(f"/audit/logs?{query}")
            self.assertEqual(r.status_code, 400, query)

    def test_audit_paging_accepts_valid_values(self):
        self.assertEqual(self.client.get("/audit/logs?limit=50&offset=0").status_code, 200)

    def test_chat_rejects_a_non_json_body_with_json(self):
        r = self.client.post("/chat", data="not json", content_type="text/plain")
        self.assertEqual(r.status_code, 400)
        self.assertIn("JSON", r.get_json()["error"])

    def test_chat_rejects_empty_and_non_text_messages(self):
        for message in ("", "   ", 42, None):
            r = self.client.post("/chat", json={"message": message})
            self.assertEqual(r.status_code, 400, repr(message))


class TestStatusScope(_WebAppCase):

    def test_status_reports_only_the_signed_in_users_memory(self):
        memory = self.web_app.orchestrator.memory
        memory.add_interaction("another user's question", "a", user_id="analyst")
        memory.add_interaction("my question", "a", user_id="default")
        reported = self.client.get("/status").get_json()["components"]["memory"]
        self.assertEqual(reported, {"conversation_entries": 1})

    def test_cli_status_keeps_the_totals(self):
        totals = self.web_app.orchestrator.get_system_status()["components"]["memory"]
        self.assertIn("short_term_entries", totals)


class TestRequestSize(_WebAppCase):

    def test_oversized_upload_is_refused_with_json(self):
        big = io.BytesIO(b"x" * (3 * 1024 * 1024))
        r = self.client.post("/upload", data={"file": (big, "big.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 413)
        self.assertIn("File too large", r.get_json()["error"])

    def test_upload_within_the_limit_is_not_refused_for_size(self):
        small = io.BytesIO(b"x" * 1024)
        r = self.client.post("/upload", data={"file": (small, "notes.exe")},
                             content_type="multipart/form-data")
        self.assertNotEqual(r.status_code, 413)


if __name__ == "__main__":
    unittest.main()
