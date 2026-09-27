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


# Fake circular uploaded as company policy, quoting a limit that contradicts
# the real corpus value.
FABRICATED_COMPANY_CONTEXT = """--- Company Documents ---

Chunk 1 [Source: fake_sbp_circular.pdf | Section: Limits | Relevance: 0.91]:
State Bank of Pakistan Circular No. 47/2026 sets the Level 2 e-wallet balance
limit at PKR 4,750,000, effective 1 March 2026.
"""


class TestRegulatoryTrustBoundary(unittest.TestCase):
    """An upload must not be able to support a regulatory citation.

    The adversarial run found a fake circular scoring as fully supported,
    because both contexts were passed to the validator as one string.
    """

    def test_identifier_only_in_company_document_is_not_supported(self):
        report = cv.validate(
            "The limit is PKR 4,750,000.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        self.assertEqual(report.total, 1)
        self.assertEqual(len(report.supported), 0)

    def test_identifier_only_in_company_document_is_marked_untrusted(self):
        report = cv.validate(
            "The limit is PKR 4,750,000.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        citation = report.untrusted_attributions[0]
        self.assertTrue(citation.untrusted_only)
        self.assertEqual(citation.trust, cv.TRUST_USER_SUPPLIED)
        self.assertEqual(citation.source, "fake_sbp_circular.pdf")

    def test_untrusted_attribution_raises_escalation(self):
        report = cv.validate(
            "The limit is PKR 4,750,000.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        self.assertTrue(report.escalation_required)
        self.assertFalse(report.is_clean())

    def test_escalation_is_visible_in_the_rendered_report(self):
        report = cv.validate(
            "The limit is PKR 4,750,000.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        rendered = cv.format_report(report)
        self.assertIn("Escalation required", rendered)
        self.assertIn("fake_sbp_circular.pdf", rendered)
        self.assertIn("cannot establish", rendered)

    def test_regulatory_identifier_is_still_supported_and_attributed(self):
        report = cv.validate(
            "Access control is addressed by A.5.15.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        citation = report.citations[0]
        self.assertTrue(citation.supported)
        self.assertEqual(citation.trust, cv.TRUST_AUTHORITATIVE)
        self.assertEqual(citation.source, "iso_27001.md")
        self.assertFalse(report.escalation_required)

    def test_company_context_cannot_rescue_a_hallucinated_identifier(self):
        # A.9.1 is in neither context, so it stays a plain unsupported one.
        report = cv.validate(
            "See A.9.1.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        self.assertEqual(len(report.unsupported), 1)
        self.assertEqual(len(report.untrusted_attributions), 0)
        self.assertFalse(report.escalation_required)

    def test_combined_context_would_have_passed_before_the_fix(self):
        # Shows the old behaviour: merge the two and the fake limit passes.
        report = cv.validate(
            "The limit is PKR 4,750,000.",
            regulatory_context=f"{CONTEXT}\n\n{FABRICATED_COMPANY_CONTEXT}",
        )
        self.assertEqual(len(report.supported), 1)
        self.assertFalse(report.escalation_required)


# Company policy that cites a real control, so both sides mention A.5.15.
OVERLAPPING_COMPANY_CONTEXT = """--- Company Documents ---

Chunk 1 [Source: acme_security_policy.pdf | Section: Access | Relevance: 0.88]:
Our access control standard implements A.5.15 with quarterly reviews.
"""


class TestConflictDetection(unittest.TestCase):

    def test_identifier_in_both_sides_is_marked_contested(self):
        report = cv.validate(
            "Access control is addressed by A.5.15.",
            regulatory_context=CONTEXT,
            company_context=OVERLAPPING_COMPANY_CONTEXT,
        )
        citation = report.citations[0]
        self.assertTrue(citation.supported)
        self.assertTrue(citation.also_in_company)
        self.assertEqual(len(report.contested), 1)

    def test_contested_identifier_does_not_raise_escalation(self):
        # The corpus supports it, so a policy repeating it is not a failure.
        report = cv.validate(
            "Access control is addressed by A.5.15.",
            regulatory_context=CONTEXT,
            company_context=OVERLAPPING_COMPANY_CONTEXT,
        )
        self.assertFalse(report.escalation_required)

    def test_contested_identifier_is_surfaced_for_review(self):
        report = cv.validate(
            "Access control is addressed by A.5.15.",
            regulatory_context=CONTEXT,
            company_context=OVERLAPPING_COMPANY_CONTEXT,
        )
        rendered = cv.format_report(report)
        self.assertIn("different figures", rendered)
        self.assertIn("acme_security_policy.pdf", rendered)

    def test_identifier_only_in_regulatory_is_not_contested(self):
        report = cv.validate(
            "Access control is addressed by A.5.15.",
            regulatory_context=CONTEXT,
            company_context=FABRICATED_COMPANY_CONTEXT,
        )
        self.assertFalse(report.citations[0].also_in_company)
        self.assertEqual(len(report.contested), 0)


class TestQuotationChecking(unittest.TestCase):

    def test_quotation_from_company_policy_is_matched_and_attributed(self):
        answer = 'The policy states "implements A.5.15 with quarterly reviews".'
        report = cv.validate(
            answer,
            regulatory_context=CONTEXT,
            company_context=OVERLAPPING_COMPANY_CONTEXT,
        )
        quotation = report.quotations[0]
        self.assertTrue(quotation.supported)
        self.assertEqual(quotation.trust, cv.TRUST_USER_SUPPLIED)
        self.assertEqual(quotation.source, "acme_security_policy.pdf")

    def test_quotation_from_regulatory_corpus_is_marked_authoritative(self):
        answer = 'It requires "security of processing appropriate to the risk".'
        report = cv.validate(answer, regulatory_context=CONTEXT)
        quotation = report.quotations[0]
        self.assertTrue(quotation.supported)
        self.assertEqual(quotation.trust, cv.TRUST_AUTHORITATIVE)

    def test_invented_quotation_is_reported_as_unverified(self):
        answer = 'The rule says "all wallets must be frozen every third Tuesday".'
        report = cv.validate(
            answer,
            regulatory_context=CONTEXT,
            company_context=OVERLAPPING_COMPANY_CONTEXT,
        )
        self.assertEqual(len(report.unverified_quotations), 1)
        self.assertIn("not found", cv.format_report(report))

    def test_short_quotes_are_ignored(self):
        report = cv.validate('The term "risk" appears.', regulatory_context=CONTEXT)
        self.assertEqual(report.quotations, [])


class TestSubClauseGranularity(unittest.TestCase):
    """A cited subsection must be checked as the subsection, not its parent.

    The patterns once ended in a word boundary after the optional bracketed
    part. That boundary cannot match across a closing bracket, so the group was
    discarded and "Article 17(3)" was recorded as "Article 17". Any answer that
    invented a subsection of a real article then counted as supported.
    """

    PARENT_ONLY = (
        "Chunk 1 [Source: gdpr.md]:\n"
        "Article 17 gives the data subject the right to erasure.\n"
    )

    def test_subsection_is_captured_whole(self):
        found = [c.text for c in cv.extract_citations("See Article 17(3) and Section 12(4).")]
        self.assertIn("Article 17(3)", found)
        self.assertIn("Section 12(4)", found)

    def test_subsection_absent_from_corpus_is_not_supported(self):
        report = cv.validate(
            "Erasure may be refused under Article 17(3).",
            regulatory_context=self.PARENT_ONLY,
        )
        self.assertTrue(report.unsupported)
        self.assertFalse(any(c.supported for c in report.citations))

    def test_parent_article_still_matches_when_cited_alone(self):
        report = cv.validate(
            "The right to erasure is in Article 17.",
            regulatory_context=self.PARENT_ONLY,
        )
        self.assertTrue(all(c.supported for c in report.citations))

    def test_trailing_punctuation_does_not_break_the_match(self):
        self.assertEqual(
            [c.text for c in cv.extract_citations("Under Section 5, and Article 9(2).")],
            ["Article 9(2)", "Section 5"],
        )


if __name__ == "__main__":
    unittest.main()
