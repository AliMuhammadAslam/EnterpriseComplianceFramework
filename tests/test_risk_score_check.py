"""Tests for the deterministic check of the Regulatory Risk Score table.

Run with:  python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import risk_score_check as rsc


def report(*rows):
    table = "\n".join(
        ["| Gap | Standard | S | L | G | Risk Score | Priority Band |",
         "|-----|----------|---|---|---|------------|---------------|"] + list(rows)
    )
    return (
        "## Gap Analysis\nSome gaps.\n\n"
        f"## {rsc.SECTION_HEADING}\n\n{table}\n\n"
        "## Recommendations\n1. Fix things."
    )


def band_cells(text):
    section = text.split(rsc.SECTION_HEADING, 1)[1].split("## Recommendations")[0]
    rows = [l for l in section.splitlines() if l.startswith("|")][2:]
    return [[c.strip() for c in r.strip("|").split("|")] for r in rows]


class TestCorrections(unittest.TestCase):

    def test_spurious_escalation_marker_is_removed(self):
        text, result = rsc.check_and_correct(report(
            "| No CDD | AML | 5 | 3 | 3 | 45 | Immediate (escalated) |"))
        self.assertEqual(band_cells(text)[0][6], "Immediate")
        self.assertEqual(len(result.corrections), 1)
        self.assertIn("already Immediate", result.corrections[0])

    def test_marker_inside_other_wording_is_removed_cleanly(self):
        text, _ = rsc.check_and_correct(report(
            "| No CDD | AML | 5 | 3 | 3 | 45 | Immediate (Short-term action, escalated) |"))
        self.assertEqual(band_cells(text)[0][6], "Immediate (Short-term action)")

    def test_missing_escalation_marker_is_added(self):
        # S=5, L=1, G=1 scores 5, Long-term by score, Medium-term by the rule.
        text, result = rsc.check_and_correct(report(
            "| Retention | SBP | 5 | 1 | 1 | 5 | Medium-term |"))
        self.assertEqual(band_cells(text)[0][6], "Medium-term (escalated)")
        self.assertIn("marker added", result.corrections[0])

    def test_wrong_band_from_unapplied_escalation_is_corrected(self):
        # S=5, G=3 must be Immediate even though 5x1x3=15 is Medium-term.
        text, result = rsc.check_and_correct(report(
            "| No CDD | AML | 5 | 1 | 3 | 15 | Medium-term |"))
        self.assertEqual(band_cells(text)[0][6], "Immediate (escalated)")
        self.assertIn("corrected to", result.corrections[0])

    def test_wrong_arithmetic_is_corrected(self):
        text, result = rsc.check_and_correct(report(
            "| Encryption | ISO | 4 | 2 | 3 | 22 | Medium-term |"))
        cells = band_cells(text)[0]
        self.assertEqual(cells[5], "24")
        self.assertEqual(cells[6], "Immediate")
        self.assertIn("22 corrected to 24", result.corrections[0])

    def test_correct_rows_are_left_untouched(self):
        original = report(
            "| Encryption | ISO | 4 | 2 | 3 | 24 | Immediate (Short-term) |",
            "| BCP | ISO 22301 | 3 | 2 | 3 | 18 | Medium-term |",
            "| Retention | SBP | 5 | 1 | 1 | 5 | Medium-term (escalated) |",
        )
        text, result = rsc.check_and_correct(original)
        self.assertEqual(text, original)
        self.assertEqual(result.rows_checked, 3)
        self.assertEqual(result.corrections, [])
        self.assertIn("every score, band and escalation marker matches", rsc.format_check(result))

    def test_rest_of_report_is_unchanged(self):
        original = report("| No CDD | AML | 5 | 3 | 3 | 45 | Immediate (escalated) |")
        text, _ = rsc.check_and_correct(original)
        self.assertEqual(text.split(rsc.SECTION_HEADING)[0], original.split(rsc.SECTION_HEADING)[0])
        self.assertTrue(text.endswith("## Recommendations\n1. Fix things."))


class TestUnreadableInput(unittest.TestCase):

    def test_report_without_the_section_is_unchanged(self):
        text, result = rsc.check_and_correct("## Executive Summary\nNo scoring here.")
        self.assertEqual(text, "## Executive Summary\nNo scoring here.")
        self.assertFalse(result.table_found)
        self.assertEqual(rsc.format_check(result), "")

    def test_unparseable_row_is_reported_not_altered(self):
        original = report("| Vague gap | AML | high | 3 | 3 | n/a | Immediate |")
        text, result = rsc.check_and_correct(original)
        self.assertEqual(text, original)
        self.assertEqual(len(result.unparsed), 1)
        self.assertIn("could not be read", rsc.format_check(result))


if __name__ == "__main__":
    unittest.main()
