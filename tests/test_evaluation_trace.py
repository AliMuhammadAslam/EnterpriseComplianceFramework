"""Tests that a compliance evaluation leaves an evidence trace behind.

The model is stubbed, so this runs without API calls.

Run with:  python -m unittest discover -s tests
"""

import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import Orchestrator
from audit.evidence_trace import EvidenceTraceStore
from evaluation.engine import EvaluationEngine

REPORT = (
    "## Executive Summary\nAccess control meets A.5.15.\n\n"
    "## Regulatory Risk Score and Prioritization\n\n"
    "| Gap | Standard | S | L | G | Risk Score | Priority Band |\n"
    "|---|---|---|---|---|---|---|\n"
    "| No CDD | AML | 5 | 3 | 3 | 45 | Immediate (escalated) |\n"
)


class _Rag:
    def retrieve_knowledge_with_results(self, query, **kwargs):
        text = "A.5.15 Access control rules shall be established."
        return (f"Chunk 1 [Source: iso_27001.md]:\n{text}",
                [{"content": text, "metadata": {"source": "iso_27001.md", "section": "Annex A"},
                  "relevance_score": 0.8}])

    def retrieve_company_docs_for_queries_with_results(self, user_id, queries, doc_ids=None):
        text = "Access is reviewed quarterly. Contact ciso@acme.pk for exceptions."
        return (f"Chunk 1 [Source: policy.pdf]:\n{text}",
                [{"content": text, "metadata": {"source": "policy.pdf", "doc_id": "d1"},
                  "relevance_score": 0.7}])


def _reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class TestEvaluationTrace(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Only the parts of the orchestrator the trace path uses.
        self.orch = Orchestrator.__new__(Orchestrator)
        self.orch.logger = mock.MagicMock()
        self.orch.trace_store = EvidenceTraceStore(trace_dir=self.tmp)
        self.orch.evaluation_engine = EvaluationEngine(_Rag())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_evaluation(self):
        with mock.patch("evaluation.engine.completion", return_value=_reply(REPORT)):
            return self.orch.evaluate_compliance_traced(
                user_id="analyst", standards=["ISO 27001"], doc_ids=["d1"]
            )

    def test_trace_is_written_and_linked_to_the_report(self):
        report, trace_id = self.run_evaluation()
        self.assertTrue(trace_id)
        trace = self.orch.trace_store.load(trace_id)
        self.assertEqual(trace.user_id, "analyst")
        self.assertEqual(trace.intent, "compliance_evaluation")
        self.assertIn("ISO 27001", trace.request)
        self.assertEqual(trace.final_answer, report)

    def test_trace_records_both_regulatory_and_company_chunks(self):
        _, trace_id = self.run_evaluation()
        sources = {c.source for c in self.orch.trace_store.load(trace_id).retrieved_chunks}
        self.assertEqual(sources, {"iso_27001.md", "policy.pdf"})

    def test_trace_records_the_checks_and_steps(self):
        _, trace_id = self.run_evaluation()
        trace = self.orch.trace_store.load(trace_id)
        self.assertEqual(trace.validation["citations"]["supported"], 1)
        self.assertEqual(trace.validation["risk_score_check"]["rows_checked"], 1)
        self.assertEqual(len(trace.validation["risk_score_check"]["corrections"]), 1)
        self.assertEqual(
            [t.name for t in trace.tool_calls],
            ["regulatory_retrieval", "company_retrieval", "report_generation",
             "risk_score_check", "citation_validation"],
        )

    def test_company_text_is_redacted_in_the_trace(self):
        _, trace_id = self.run_evaluation()
        with open(os.path.join(self.tmp, f"trace_{trace_id}.json"), encoding="utf-8") as f:
            written = f.read()
        self.assertNotIn("ciso@acme.pk", written)

    def test_a_trace_failure_does_not_fail_the_evaluation(self):
        with mock.patch.object(self.orch.trace_store, "save", side_effect=OSError("disk full")):
            report, trace_id = self.run_evaluation()
        self.assertIn("Executive Summary", report)
        self.assertEqual(trace_id, "")

    def test_plain_evaluate_compliance_still_returns_only_the_report(self):
        with mock.patch("evaluation.engine.completion", return_value=_reply(REPORT)):
            report = self.orch.evaluate_compliance(user_id="analyst", standards=["ISO 27001"])
        self.assertIsInstance(report, str)


if __name__ == "__main__":
    unittest.main()
