"""Tests for how the command-line interface reports full and partial failures.

Run with:  python -m unittest discover -s tests
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.orchestrator import OrchestrationResult
from main import AgentCLI

SUCCESS = OrchestrationResult(success=True, result="full answer",
                              strategy_used="plan_and_execute", steps_executed=3)
PARTIAL = OrchestrationResult(success=False, result="answer from the steps that worked",
                              strategy_used="plan_and_execute", steps_executed=3,
                              error="Step 2 failed: upstream timeout")
FAILURE = OrchestrationResult(success=False, result="I encountered an error while processing your request.",
                              strategy_used="error", error="connection refused")


def _cli(result):
    cli = AgentCLI.__new__(AgentCLI)  # skip building a real orchestrator
    cli.orchestrator = mock.MagicMock()
    cli.orchestrator.run.return_value = result
    cli.logger = mock.MagicMock()
    return cli


def _interactive(result):
    out = io.StringIO()
    with mock.patch("builtins.input", side_effect=["a question", "quit"]), redirect_stdout(out):
        _cli(result).interactive_mode()
    return out.getvalue()


class TestInteractiveOutput(unittest.TestCase):

    def test_partial_failure_is_shown_as_an_answer_with_a_note(self):
        out = _interactive(PARTIAL)
        self.assertIn("Agent: answer from the steps that worked", out)
        self.assertIn("Note: part of this request failed: Step 2 failed", out)
        self.assertNotIn("Error: answer from the steps that worked", out)

    def test_total_failure_is_still_an_error(self):
        out = _interactive(FAILURE)
        self.assertIn("Error: I encountered an error", out)
        self.assertIn("Details: connection refused", out)

    def test_success_is_unchanged(self):
        out = _interactive(SUCCESS)
        self.assertIn("Agent: full answer", out)
        self.assertIn("with 3 steps", out)
        self.assertNotIn("Note:", out)


class TestBatchOutput(unittest.TestCase):

    def test_partial_failure_is_not_silent(self):
        text = _cli(PARTIAL).batch_mode("q")
        self.assertTrue(text.startswith("answer from the steps that worked"))
        self.assertIn("Note: part of this request failed", text)

    def test_success_returns_only_the_answer(self):
        self.assertEqual(_cli(SUCCESS).batch_mode("q"), "full answer")


if __name__ == "__main__":
    unittest.main()
