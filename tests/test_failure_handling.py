"""Tests that a failed LLM call is reported as a failure, not as content.

The model is stubbed, so this runs without API calls.

Run with:  python -m unittest discover -s tests
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.executor import Executor
from agent.planner import Plan, PlanStep
from evaluation.engine import EvaluationEngine

COMPILE_MARKER = "summarising analysis results"


def _reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _FakeModel:
    """Answers each plan step, failing the steps listed in fail_on."""

    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.compile_inputs = []

    def __call__(self, model, messages, **kwargs):
        system, user = messages[0]["content"], messages[1]["content"]
        if COMPILE_MARKER in system:
            self.compile_inputs.append(user)
            return _reply("compiled answer")
        for number in self.fail_on:
            if f"Task: step {number}" in user:
                raise ConnectionError(f"upstream timeout on step {number}")
        task = user.split("Task: ", 1)[1]
        return _reply(f"result of {task}")


def _plan(*steps):
    return Plan(goal="the question", steps=list(steps))


class TestExecutorFailures(unittest.TestCase):

    def run_plan(self, plan, model):
        with mock.patch("agent.executor.completion", side_effect=model):
            return Executor().execute_plan(plan)

    def test_all_steps_succeeding_is_a_success(self):
        model = _FakeModel()
        result = self.run_plan(
            _plan(PlanStep(step_number=1, description="step 1"),
                  PlanStep(step_number=2, description="step 2")),
            model,
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertEqual(result.result, "compiled answer")

    def test_failed_call_marks_the_step_failed(self):
        result = self.run_plan(
            _plan(PlanStep(step_number=1, description="step 1"),
                  PlanStep(step_number=2, description="step 2")),
            _FakeModel(fail_on={2}),
        )
        self.assertFalse(result.success)
        self.assertTrue(result.step_results[0]["success"])
        self.assertFalse(result.step_results[1]["success"])
        self.assertIn("step 2", result.error.lower())
        self.assertIn("upstream timeout", result.error)

    def test_error_text_is_not_fed_into_the_answer(self):
        model = _FakeModel(fail_on={2})
        self.run_plan(
            _plan(PlanStep(step_number=1, description="step 1"),
                  PlanStep(step_number=2, description="step 2")),
            model,
        )
        self.assertEqual(len(model.compile_inputs), 1)
        self.assertIn("result of step 1", model.compile_inputs[0])
        self.assertNotIn("upstream timeout", model.compile_inputs[0])
        self.assertNotIn("Error executing step", model.compile_inputs[0])

    def test_step_depending_on_a_failed_step_does_not_run(self):
        result = self.run_plan(
            _plan(PlanStep(step_number=1, description="step 1"),
                  PlanStep(step_number=2, description="step 2", dependencies=[1])),
            _FakeModel(fail_on={1}),
        )
        self.assertFalse(result.step_results[1]["success"])
        self.assertIn("Dependencies not met", result.step_results[1]["error"])

    def test_every_step_failing_gives_no_invented_answer(self):
        model = _FakeModel(fail_on={1})
        result = self.run_plan(_plan(PlanStep(step_number=1, description="step 1")), model)
        self.assertFalse(result.success)
        self.assertEqual(result.result, "I was unable to complete the requested task.")
        self.assertEqual(model.compile_inputs, [])


class _FakeRag:
    def retrieve_company_docs_for_queries_with_results(self, user_id, queries, doc_ids=None):
        text = "Access reviewed quarterly."
        context = f"--- Company Documents ---\n\nChunk 1 [Source: policy.pdf]:\n{text}"
        return context, [{"content": text, "metadata": {"source": "policy.pdf"}}]

    def retrieve_knowledge_with_results(self, query, **kwargs):
        text = "A.5.15 Access control."
        context = f"--- Regulatory Knowledge Base ---\n\nChunk 1 [Source: iso_27001.md]:\n{text}"
        return context, [{"content": text, "metadata": {"source": "iso_27001.md"}}]


class TestEvaluationFailures(unittest.TestCase):

    def test_failed_generation_raises_instead_of_returning_a_report(self):
        engine = EvaluationEngine(_FakeRag())
        with mock.patch("evaluation.engine.completion",
                        side_effect=ConnectionError("rate limited")):
            with self.assertRaises(RuntimeError) as ctx:
                engine.evaluate_compliance(user_id="default", standards=["ISO 27001"])
        self.assertIn("rate limited", str(ctx.exception))

    def test_missing_regulatory_context_stops_the_evaluation(self):
        """An unavailable index must fail the run, not produce an unsupported report."""
        rag = _FakeRag()
        rag.retrieve_knowledge_with_results = lambda query, **kwargs: (
            "[No relevant results found in Regulatory Knowledge Base.]", []
        )
        engine = EvaluationEngine(rag)
        with mock.patch("evaluation.engine.completion") as model:
            with self.assertRaises(RuntimeError) as ctx:
                engine.evaluate_compliance(user_id="default", standards=["ISO 27001"])
        self.assertIn("ISO 27001", str(ctx.exception))
        model.assert_not_called()

    def test_successful_generation_still_returns_the_report(self):
        engine = EvaluationEngine(_FakeRag())
        with mock.patch("evaluation.engine.completion",
                        return_value=_reply("## Executive Summary\nAll good under A.5.15.")):
            report = engine.evaluate_compliance(user_id="default", standards=["ISO 27001"])
        self.assertIn("Executive Summary", report)
        self.assertIn("Citation Validation", report)


if __name__ == "__main__":
    unittest.main()
