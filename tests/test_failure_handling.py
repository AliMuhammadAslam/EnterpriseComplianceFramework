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



def _plan_reply(n_steps, dependencies=None):
    import json as _json
    steps = [{"step_number": i, "description": f"step {i}", "tool_required": None,
              "input_data": {}, "dependencies": (dependencies or {}).get(i, [])}
             for i in range(1, n_steps + 1)]
    return _reply(_json.dumps({"goal": "g", "steps": steps}))


class TestPlanner(unittest.TestCase):

    def _plan(self, reply, **env):
        from agent.planner import Planner
        with mock.patch.dict(os.environ, env), \
             mock.patch("agent.planner.completion", return_value=reply) as model:
            plan = Planner().create_plan(SimpleNamespace(
                structured_input={"original_content": "a question"}, intent="information_seeking"))
        return plan, model

    def test_model_is_asked_for_json_output(self):
        _, model = self._plan(_plan_reply(2))
        self.assertEqual(model.call_args.kwargs.get("response_format"), {"type": "json_object"})

    def test_long_plan_is_cut_to_the_limit(self):
        plan, _ = self._plan(_plan_reply(10))
        self.assertEqual([s.step_number for s in plan.steps], [1, 2, 3, 4, 5, 6])

    def test_limit_comes_from_the_environment(self):
        plan, _ = self._plan(_plan_reply(10), MAX_PLAN_STEPS="3")
        self.assertEqual(len(plan.steps), 3)

    def test_dependencies_on_dropped_steps_are_removed(self):
        plan, _ = self._plan(_plan_reply(8, dependencies={2: [1, 7]}), MAX_PLAN_STEPS="3")
        self.assertEqual(plan.steps[1].dependencies, [1])

    def test_dependency_written_as_text_does_not_reject_the_plan(self):
        plan, _ = self._plan(_plan_reply(3, dependencies={3: ["step_number: 2", "1", "none"]}))
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[2].dependencies, [2, 1])

    def test_dependency_on_a_missing_step_is_removed(self):
        plan, _ = self._plan(_plan_reply(3, dependencies={3: [1, 9]}))
        self.assertEqual(plan.steps[2].dependencies, [1])

    def test_unsupported_settings_are_dropped_for_other_models(self):
        _, model = self._plan(_plan_reply(2))
        self.assertTrue(model.call_args.kwargs.get("drop_params"))

    def test_short_plan_is_unchanged(self):
        plan, _ = self._plan(_plan_reply(4))
        self.assertEqual(len(plan.steps), 4)

    def test_unparseable_reply_still_falls_back_to_one_step(self):
        plan, _ = self._plan(_reply("not json"))
        self.assertEqual(len(plan.steps), 1)


class TestCommandLineUser(unittest.TestCase):

    def test_batch_mode_uses_the_cli_user_not_the_web_default(self):
        import main
        cli = main.AgentCLI.__new__(main.AgentCLI)
        cli.logger = mock.Mock()
        cli.orchestrator = mock.Mock()
        cli.orchestrator.run.return_value = SimpleNamespace(result="answer", error=None)
        self.assertEqual(cli.batch_mode("a question"), "answer")
        self.assertEqual(cli.orchestrator.run.call_args.kwargs.get("user_id"), "cli_user")


if __name__ == "__main__":
    unittest.main()
