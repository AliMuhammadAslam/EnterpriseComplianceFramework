"""Tests for the dashboard figures read from saved evaluation reports.

Run with:  python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.dashboard import build_dashboard, parse_coverage, parse_risks, summarise_report

REPORT = """# Compliance Evaluation Report

## Executive Summary
Two gaps were found.

## Standards Coverage

| Standard | Status | Note |
|----------|--------|------|
| Pakistan AML/CFT | Findings | Procedures present. |
| **GDPR** | Documentation gap | No GDPR policy. |
| PCI DSS | Not applicable | No card data. |

## Regulatory Risk Score and Prioritization

| Gap | Standard | S | L | G | Risk Score | Priority Band |
|-----|----------|---|---|---|------------|---------------|
| Record retention | Pakistan AML/CFT | 5 | 3 | 2 | 30 | Immediate |
| Breach notification | GDPR | 4 | 2 | 1 | 8 | Long-term (escalated) |

## Recommendations
1. Fix retention.
"""


class TestCoverage(unittest.TestCase):

    def test_reads_each_standard_and_its_status(self):
        result = parse_coverage(REPORT)
        self.assertTrue(result["found"])
        self.assertEqual(result["rows"], [
            {"standard": "Pakistan AML/CFT", "status": "Findings"},
            {"standard": "GDPR", "status": "Documentation gap"},
            {"standard": "PCI DSS", "status": "Not applicable"},
        ])

    def test_unknown_status_is_counted_not_guessed(self):
        text = REPORT.replace("| PCI DSS | Not applicable |", "| PCI DSS | Partially |")
        result = parse_coverage(text)
        self.assertEqual([r["standard"] for r in result["rows"]], ["Pakistan AML/CFT", "GDPR"])
        self.assertEqual(result["unparsed"], 1)

    def test_missing_table(self):
        self.assertEqual(parse_coverage("## Executive Summary\nNo tables."),
                         {"found": False, "rows": [], "unparsed": 0})


class TestRisks(unittest.TestCase):

    def test_reads_scores_bands_and_escalation(self):
        result = parse_risks(REPORT)
        self.assertTrue(result["found"])
        self.assertEqual(result["rows"][0], {
            "gap": "Record retention", "standard": "Pakistan AML/CFT",
            "s": 5, "l": 3, "g": 2, "score": 30, "band": "Immediate", "escalated": False,
        })
        self.assertEqual(result["rows"][1]["band"], "Long-term")
        self.assertTrue(result["rows"][1]["escalated"])

    def test_malformed_rows_are_counted_and_skipped(self):
        text = REPORT.replace("| 4 | 2 | 1 | 8 |", "| four | 2 | 1 | 8 |")
        result = parse_risks(text)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["unparsed"], 1)

    def test_row_with_unknown_band_is_skipped(self):
        text = REPORT.replace("| 30 | Immediate |", "| 30 | Urgent |")
        result = parse_risks(text)
        self.assertEqual([r["gap"] for r in result["rows"]], ["Breach notification"])
        self.assertEqual(result["unparsed"], 1)

    def test_columns_in_a_different_order(self):
        reordered ="""## Regulatory Risk Score and Prioritization

| Standard | Gap | Priority Band | Risk Score | G | L | S |
|---|---|---|---|---|---|---|
| GDPR | Breach notification | Long-term | 8 | 1 | 2 | 4 |
"""
        row = parse_risks(reordered)["rows"][0]
        self.assertEqual((row["standard"], row["gap"], row["s"], row["l"], row["g"], row["score"]),
                         ("GDPR", "Breach notification", 4, 2, 1, 8))

    def test_table_without_a_separator_row_keeps_its_first_row(self):
        text = ("## Regulatory Risk Score and Prioritization\n\n"
                "| Gap | Standard | S | L | G | Risk Score | Priority Band |\n"
                "| Breach notice | GDPR | 4 | 2 | 3 | 24 | Immediate |\n")
        self.assertEqual([r["gap"] for r in parse_risks(text)["rows"]], ["Breach notice"])

    def test_score_is_computed_from_its_factors(self):
        text = REPORT.replace("| 4 | 2 | 1 | 8 |", "| 4 | 2 | 1 | 8.0 |")
        self.assertEqual(parse_risks(text)["rows"][1]["score"], 8)

    def test_factor_outside_its_range_is_counted_and_skipped(self):
        text = REPORT.replace("| 4 | 2 | 1 | 8 |", "| 4 | 4 | 1 | 16 |")
        result = parse_risks(text)
        self.assertEqual([r["gap"] for r in result["rows"]], ["Record retention"])
        self.assertEqual(result["unparsed"], 1)

    def test_factor_columns_named_in_full(self):
        text = """## Regulatory Risk Score and Prioritization

| Gap | Standard | Severity (S) | Likelihood (L) | Regulatory Gravity (G) | Priority Band |
|---|---|---|---|---|---|
| Breach notice | GDPR | 4 | 2 | 3 | Immediate |
"""
        row = parse_risks(text)["rows"][0]
        self.assertEqual((row["s"], row["l"], row["g"], row["score"]), (4, 2, 3, 24))

    def test_table_under_a_later_heading_is_not_used(self):
        text = "## Regulatory Risk Score and Prioritization\nNo gaps.\n\n## Recommendations\n" \
               "| Gap | Standard | S | L | G | Risk Score | Priority Band |\n|-|-|-|-|-|-|-|\n" \
               "| X | Y | 1 | 1 | 1 | 1 | Long-term |\n"
        self.assertFalse(parse_risks(text)["found"])


class TestDashboard(unittest.TestCase):

    def test_reports_are_ordered_oldest_first(self):
        records = [
            {"report_id": "b", "timestamp": "2026-11-13T10:00:00", "standards": ["GDPR"], "report_text": REPORT},
            {"report_id": "a", "timestamp": "2026-11-12T10:00:00", "standards": ["GDPR"], "report_text": REPORT},
        ]
        data = build_dashboard(records)
        self.assertEqual([r["report_id"] for r in data["reports"]], ["a", "b"])
        self.assertEqual(data["bands"], ["Immediate", "Medium-term", "Long-term"])

    def test_report_without_tables_still_appears(self):
        summary = summarise_report({"report_id": "x", "timestamp": "t", "report_text": "Plain text."})
        self.assertFalse(summary["coverage_found"])
        self.assertFalse(summary["risk_table_found"])
        self.assertEqual(summary["gaps"], [])


if __name__ == "__main__":
    unittest.main()
