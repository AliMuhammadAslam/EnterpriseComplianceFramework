"""Tests for the citation validator.

Run with:  python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import citation_validator as cv


# Shaped like the output of RAGPipeline._format_section so the tests exercise
# the same chunk headers the validator will meet in production.
CONTEXT = """--- Regulatory Knowledge Base ---

Chunk 1 [Source: iso_27001.md | Section: Annex A Theme 1 | Relevance: 0.87]:
A.5.1 Policies for information security. A.5.15 Access control.
Clause 6 covers planning for the information security management system.

Chunk 2 [Source: gdpr.md | Section: Data Subject Rights | Relevance: 0.81]:
Article 32 requires security of processing appropriate to the risk.

Chunk 3 [Source: peca_2016.md | Section: Offences | Relevance: 0.75]:
Section 21 concerns offences against modesty. A fine up to PKR 50,000 applies.
"""


class TestExtraction(unittest.TestCase):

    def test_extracts_each_identifier_style(self):
        text = (
            "Per A.5.1 and Article 32, plus Section 21, Clause 6, "
            "Requirement 3.2 and a threshold of PKR 50,000."
        )
        kinds = {c.kind for c in cv.extract_citations(text)}
        self.assertEqual(
            kinds,
            {"iso_control", "article", "section", "clause", "requirement", "monetary"},
        )

    def test_deduplicates_repeated_identifiers(self):
        text = "A.5.1 is relevant. Again, A.5.1 applies. And A.5.1 once more."
        self.assertEqual(len(cv.extract_citations(text)), 1)

    def test_no_identifiers_in_named_criteria_standards(self):
        # NIST CSF and SOC 2 carry no numeric scheme in this corpus, so text
        # about them must not produce phantom citations.
        text = (
            "The Govern (GV) and Identify (ID) functions of NIST CSF, and the "
            "SOC 2 Trust Service Criteria for Security and Availability."
        )
        self.assertEqual(cv.extract_citations(text), [])

    def test_overlapping_patterns_counted_once(self):
        # A.8.24 must register as one iso_control, not also as a stray number.
        citations = cv.extract_citations("Control A.8.24 applies.")
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].kind, "iso_control")


class TestValidation(unittest.TestCase):

    def test_supported_identifier_is_matched_and_attributed(self):
        report = cv.validate("Access control is addressed by A.5.15.", CONTEXT)
        self.assertEqual(report.total, 1)
        self.assertTrue(report.citations[0].supported)
        self.assertEqual(report.citations[0].source, "iso_27001.md")
        self.assertIn("A.5.15", report.citations[0].evidence)

    def test_unsupported_identifier_is_flagged(self):
        # A.9.1 is the superseded 2013 numbering and is not in the context.
        report = cv.validate("Access control is addressed by A.9.1.", CONTEXT)
        self.assertEqual(len(report.unsupported), 1)
        self.assertEqual(report.unsupported[0].text, "A.9.1")
        self.assertFalse(report.is_clean())

    def test_mixed_answer_reports_precision(self):
        report = cv.validate("See A.5.1, Article 32, and A.9.1.", CONTEXT)
        self.assertEqual(report.total, 3)
        self.assertEqual(len(report.supported), 2)
        self.assertEqual(len(report.unsupported), 1)
        self.assertAlmostEqual(report.precision, 0.6667, places=3)

    def test_monetary_threshold_matches_despite_separator(self):
        report = cv.validate("The fine is PKR 50000.", CONTEXT)
        self.assertTrue(report.citations[0].supported)

    def test_precision_is_none_when_nothing_cited(self):
        report = cv.validate("This report makes no specific citation.", CONTEXT)
        self.assertEqual(report.total, 0)
        self.assertIsNone(report.precision)


class TestAbstention(unittest.TestCase):

    def test_missing_company_documents_requires_abstention(self):
        context = (
            "⚠ IMPORTANT - NO COMPANY DOCUMENTS AVAILABLE: "
            "This user has not uploaded any company documents."
        )
        self.assertTrue(cv.requires_abstention(context))

    def test_empty_context_requires_abstention(self):
        self.assertTrue(cv.requires_abstention(""))
        self.assertTrue(cv.requires_abstention("   "))

    def test_usable_context_does_not_require_abstention(self):
        self.assertFalse(cv.requires_abstention(CONTEXT))

    def test_abstention_makes_report_unclean_even_with_no_citations(self):
        report = cv.validate("No findings.", "")
        self.assertTrue(report.abstention_required)
        self.assertFalse(report.is_clean())


class TestAnnotation(unittest.TestCase):

    def test_unsupported_identifiers_marked_inline(self):
        answer = "Refer to A.9.1 for access control."
        report = cv.validate(answer, CONTEXT)
        annotated = cv.annotate(answer, report)
        self.assertIn("[UNVERIFIED: A.9.1]", annotated)

    def test_supported_identifiers_left_untouched(self):
        answer = "Refer to A.5.1 for policies."
        report = cv.validate(answer, CONTEXT)
        self.assertEqual(cv.annotate(answer, report), answer)


class TestFormatting(unittest.TestCase):

    def test_report_names_unsupported_identifiers(self):
        report = cv.validate("See A.5.1 and A.9.1.", CONTEXT)
        rendered = cv.format_report(report)
        self.assertIn("Citation Validation", rendered)
        self.assertIn("A.9.1", rendered)
        self.assertIn("1 unsupported", rendered)

    def test_report_confirms_when_all_supported(self):
        rendered = cv.format_report(cv.validate("See A.5.1.", CONTEXT))
        self.assertIn("Every cited identifier was located", rendered)

    def test_report_states_when_nothing_cited(self):
        rendered = cv.format_report(cv.validate("No citations here.", CONTEXT))
        self.assertIn("No regulatory identifiers were cited", rendered)


if __name__ == "__main__":
    unittest.main()
