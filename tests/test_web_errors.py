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


class TestPageAndHistory(_WebAppCase):

    def test_main_page_renders_for_a_signed_in_user(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"KB_STANDARDS_COUNT = 0", r.data)

    def test_chat_history_returns_only_this_users_exchanges(self):
        memory = self.web_app.orchestrator.memory
        memory.add_interaction("mine", "answer", user_id="default")
        memory.add_interaction("theirs", "answer", user_id="someone_else")
        r = self.client.get("/chat/history")
        self.assertEqual(r.status_code, 200)
        queries = [h["query"] for h in r.get_json()["history"]]
        self.assertIn("mine", queries)
        self.assertNotIn("theirs", queries)

    def test_chat_history_needs_a_session(self):
        r = self.web_app.app.test_client().get("/chat/history")
        self.assertEqual(r.status_code, 401)


class TestRejectedUploadIsAudited(_WebAppCase):
    """A refused upload is still an attempt, and belongs in the audit trail."""

    def _failures(self):
        return self.web_app.audit.query(
            user_id="default", action="DOCUMENT_UPLOAD", status="failure", limit=50
        )

    def test_contents_not_matching_the_extension_is_recorded(self):
        # Allowed extension, so the extension check passes and validation
        # rejects it on its contents instead. That path logged nothing.
        png = io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
        r = self.client.post("/upload", data={"file": (png, "picture.pdf")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertIn("do not match", r.get_json()["error"])

        recorded = [e for e in self._failures()
                    if e["details"].get("filename") == "picture.pdf"]
        self.assertEqual(len(recorded), 1, "the refused upload was not audited")
        self.assertIn("do not match", recorded[0]["details"]["rejected"])

    def test_unsupported_extension_is_still_recorded(self):
        r = self.client.post("/upload", data={"file": (io.BytesIO(b"x"), "notes.exe")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(any(e["details"].get("filename") == "notes.exe"
                            for e in self._failures()))



class TestExecutionLogTimes(_WebAppCase):
    """Each execution log line shows when it happened, not when the request ended."""

    def test_chat_log_lines_keep_their_own_times(self):
        from datetime import datetime
        from agent.orchestrator import OrchestrationResult
        times = iter([datetime(2026, 1, 1, 9, 0, 1), datetime(2026, 1, 1, 9, 0, 5),
                      datetime(2026, 1, 1, 9, 0, 9)])
        clock = mock.Mock(now=lambda: next(times))

        def run(*args, **kwargs):
            print("[PLANNER] Created plan with 2 steps")
            print("[EXECUTOR] Step 1 completed")
            return OrchestrationResult(success=True, result="answer",
                                       strategy_used="plan_and_execute")

        with mock.patch.object(self.web_app.orchestrator, "run", side_effect=run), \
             mock.patch("utils.output_capture.datetime", clock):
            r = self.client.post("/chat", json={"message": "q", "verbose": True})

        self.assertEqual(r.get_json()["logs"], [
            "[09:00:01] [PLANNER] Created plan with 2 steps",
            "[09:00:05] [EXECUTOR] Step 1 completed",
        ])


if __name__ == "__main__":
    unittest.main()
