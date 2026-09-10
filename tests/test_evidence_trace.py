"""Tests for evidence traces and redaction.

Run with:  python -m unittest discover -s tests
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.evidence_trace import (
    EvidenceTrace,
    EvidenceTraceStore,
    RetrievedChunk,
    ToolCall,
    redact,
)


class TestRedaction(unittest.TestCase):

    def test_cnic_is_redacted(self):
        self.assertEqual(
            redact("Customer CNIC 42101-1234567-8 on file"),
            "Customer CNIC [REDACTED:cnic] on file",
        )

    def test_email_is_redacted(self):
        self.assertIn("[REDACTED:email]", redact("contact ali.aslam@example.com.pk today"))

    def test_phone_is_redacted(self):
        self.assertIn("[REDACTED:phone]", redact("call 03001234567 for support"))

    def test_card_number_is_redacted(self):
        self.assertIn("[REDACTED:card]", redact("card 4111 1111 1111 1111 declined"))

    def test_api_key_is_redacted(self):
        self.assertIn("[REDACTED:api_key]", redact("key sk-abcdefghij1234567890 leaked"))

    def test_cnic_is_not_mislabelled_as_a_card(self):
        # A CNIC is thirteen digits, so pattern order decides the label.
        self.assertIn("[REDACTED:cnic]", redact("CNIC 42101-1234567-8"))
        self.assertNotIn("card", redact("CNIC 42101-1234567-8"))

    def test_regulatory_identifiers_survive_redaction(self):
        # Over-redaction would destroy the clause numbering the trace exists for.
        text = "Control A.8.12 and Requirement 3.4 and Article 5(1) and Section 42"
        self.assertEqual(redact(text), text)

    def test_penalty_amounts_survive_redaction(self):
        self.assertEqual(redact("a fine of PKR 5,000,000"), "a fine of PKR 5,000,000")

    def test_numbered_list_is_not_treated_as_a_card(self):
        text = "steps 1 2 3 4 5 6 7 8 9 10 11 12 13 14"
        self.assertEqual(redact(text), text)

    def test_empty_input_is_safe(self):
        self.assertEqual(redact(""), "")


class TestRetrievedChunk(unittest.TestCase):

    def test_content_is_hashed_not_stored(self):
        content = "A.8.12 Data leakage prevention measures shall be applied."
        chunk = RetrievedChunk.from_result({
            "content": content,
            "metadata": {"source": "iso27001.md", "section": "A.8"},
            "relevance_score": 0.87,
        })
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertEqual(chunk.content_sha256, expected)
        self.assertEqual(chunk.source, "iso27001.md")

    def test_a_reviewer_can_confirm_which_chunk_was_used(self):
        content = "Requirement 3.4 PAN must be rendered unreadable."
        chunk = RetrievedChunk.from_result({"content": content, "metadata": {}})

        # Re-hashing the original chunk proves it is the one that was retrieved.
        rehashed = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertEqual(chunk.content_sha256, rehashed)

        # A different chunk does not match.
        other = hashlib.sha256(b"Requirement 3.5 something else").hexdigest()
        self.assertNotEqual(chunk.content_sha256, other)

    def test_preview_is_redacted_and_bounded(self):
        chunk = RetrievedChunk.from_result({
            "content": "Holder 42101-1234567-8 " + ("x" * 500),
            "metadata": {},
        })
        self.assertIn("[REDACTED:cnic]", chunk.preview)
        self.assertLessEqual(len(chunk.preview), 160)

    def test_missing_metadata_does_not_raise(self):
        chunk = RetrievedChunk.from_result({"content": "text"})
        self.assertEqual(chunk.source, "unknown")


class TestTraceStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = EvidenceTraceStore(trace_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sample(self):
        return self.store.build(
            request="Are we compliant with PCI DSS? Contact ali@example.com",
            user_id="john",
            intent="compliance_check",
            model_configuration={"model": "gpt-4o-2024-08-06", "seed": 42},
            retrieved=[{
                "content": "Requirement 3.4 PAN must be unreadable.",
                "metadata": {"source": "pcidss.md"},
                "relevance_score": 0.9,
            }],
            plan={"goal": "assess PCI DSS", "steps": []},
            tool_calls=[ToolCall(name="rag_retrieval", outcome="1 chunk")],
            final_answer="One gap found under Requirement 3.4.",
        )

    def test_request_is_redacted_before_storage(self):
        trace = self._sample()
        self.assertIn("[REDACTED:email]", trace.request)
        self.assertNotIn("ali@example.com", trace.request)

    def test_trace_captures_every_required_element(self):
        trace = self._sample()
        self.assertTrue(trace.request)
        self.assertTrue(trace.model_configuration)
        self.assertTrue(trace.retrieved_chunks)
        self.assertTrue(trace.plan)
        self.assertTrue(trace.tool_calls)
        self.assertTrue(trace.final_answer)
        self.assertTrue(trace.recorded_at_utc)

    def test_round_trip_preserves_the_trace(self):
        trace = self._sample()
        self.store.save(trace)

        loaded = self.store.load(trace.trace_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.trace_id, trace.trace_id)
        self.assertEqual(loaded.final_answer, trace.final_answer)
        self.assertEqual(
            loaded.retrieved_chunks[0].content_sha256,
            trace.retrieved_chunks[0].content_sha256,
        )

    def test_saved_file_does_not_contain_raw_chunk_text(self):
        secret = "Holder 42101-1234567-8 holds account balance details."
        trace = self.store.build(
            request="check",
            retrieved=[{"content": secret, "metadata": {"source": "policy.pdf"}}],
        )
        path = self.store.save(trace)
        with open(path, "r", encoding="utf-8") as f:
            written = f.read()

        self.assertNotIn("42101-1234567-8", written)
        self.assertIn("policy.pdf", written)

    def test_loading_an_unknown_trace_returns_none(self):
        self.assertIsNone(self.store.load("does-not-exist"))

    def test_human_override_is_recorded_without_losing_the_original(self):
        trace = self._sample()
        trace.add_override(
            reviewer="compliance_officer",
            field_name="priority_band",
            original="Medium term",
            replacement="Immediate",
            reason="regulator raised this in the last inspection",
        )
        self.store.save(trace)

        loaded = self.store.load(trace.trace_id)
        self.assertEqual(len(loaded.human_overrides), 1)
        override = loaded.human_overrides[0]
        self.assertEqual(override.original, "Medium term")
        self.assertEqual(override.replacement, "Immediate")
        self.assertEqual(override.reviewer, "compliance_officer")

    def test_empty_retrieval_produces_a_valid_trace(self):
        trace = self.store.build(request="hello", retrieved=[])
        self.store.save(trace)
        self.assertEqual(self.store.load(trace.trace_id).retrieved_chunks, [])


class TestPlanNormalisation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = EvidenceTraceStore(trace_dir=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pydantic_plan_is_converted(self):
        from agent.planner import Plan, PlanStep

        plan = Plan(goal="assess", steps=[PlanStep(step_number=1, description="retrieve")])
        trace = self.store.build(request="q", plan=plan)
        self.assertEqual(trace.plan["goal"], "assess")

    def test_none_plan_is_allowed(self):
        self.assertIsNone(self.store.build(request="q", plan=None).plan)


if __name__ == "__main__":
    unittest.main()
