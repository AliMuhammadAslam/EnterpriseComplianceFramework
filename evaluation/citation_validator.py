"""Deterministic verification of regulatory citations against retrieved context.

The system prompt asks the model to cite only identifiers that appear in the
retrieved context, but a prompt instruction is a request rather than a control.
This module enforces the same rule outside the model: it extracts every
regulatory identifier and monetary threshold from a generated answer, checks
each one against the text actually retrieved, and reports which are supported.

Identifier patterns are derived from the schemes present in the knowledge base:
ISO/IEC 27001 Annex A controls and clauses, GDPR articles, PECA sections, PCI
DSS requirements, and Pakistani Rupee thresholds. Standards that carry no
numeric scheme in the corpus, such as NIST CSF functions and the SOC 2 Trust
Service Criteria, produce no identifiers and are therefore neither supported
nor flagged.

Regulatory and company context are checked separately. Only the regulatory
corpus can support a regulatory citation. An identifier that appears solely in
an uploaded company document is flagged for escalation instead of being counted
as supported, since an upload cannot establish the obligation it claims.

Scope: this checks that a cited identifier exists in an authorised chunk and
records where it was found. It does not judge whether the cited provision
semantically entails the conclusion drawn from it; that remains open.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Trust levels for retrieved evidence.
TRUST_AUTHORITATIVE = "authoritative"
TRUST_USER_SUPPLIED = "user_supplied"

# Ordered longest-first so that a more specific pattern wins where two overlap.
CITATION_PATTERNS: List[Tuple[str, str]] = [
    ("iso_control", r"\bA\.\d+\.\d+\b"),
    ("requirement", r"\bRequirement\s+\d+(?:\.\d+)*\b"),
    # (?!\w) rather than \b: a trailing \b cannot match across
    # ")", so the optional sub-clause was dropped and "Article 17(3)" became
    # "Article 17", letting a subsection absent from the corpus count as found.
    ("article", r"\bArticle\s+\d+(?:\(\d+\))?(?!\w)"),
    ("section", r"\bSection\s+\d+(?:\(\d+\))?(?!\w)"),
    ("clause", r"\bClause\s+\d+(?:\.\d+)*\b"),
    ("monetary", r"\bPKR\s*[\d,]+(?:\.\d+)?\b"),
]

# Markers the RAG pipeline injects when it has nothing useful to offer.
_NO_EVIDENCE_MARKERS = [
    "NO COMPANY DOCUMENTS AVAILABLE",
    "No relevant context found",
    "No relevant results found",
    "No company documents have been uploaded",
]

_CHUNK_HEADER = re.compile(r"Chunk\s+\d+\s+\[Source:\s*([^\]|]+?)\s*(?:\||\])")

# Quoted passages the report attributes to a policy. Short quotes are skipped
# because they match too loosely to mean anything.
_QUOTED_PASSAGE = re.compile(r"[\"“]([^\"”\n]{15,300})[\"”]")


@dataclass
class Citation:
    """A single regulatory identifier found in a generated answer."""

    text: str
    kind: str
    normalised: str
    supported: bool = False
    source: Optional[str] = None
    evidence: Optional[str] = None
    trust: Optional[str] = None
    untrusted_only: bool = False
    also_in_company: bool = False
    company_source: Optional[str] = None


@dataclass
class Quotation:
    """A passage the answer quotes, checked against what was retrieved."""

    text: str
    supported: bool = False
    trust: Optional[str] = None
    source: Optional[str] = None


@dataclass
class ValidationReport:
    """Outcome of checking every citation in one answer."""

    citations: List[Citation] = field(default_factory=list)
    quotations: List[Quotation] = field(default_factory=list)
    abstention_required: bool = False

    @property
    def supported(self) -> List[Citation]:
        return [c for c in self.citations if c.supported]

    @property
    def unsupported(self) -> List[Citation]:
        return [c for c in self.citations if not c.supported]

    @property
    def untrusted_attributions(self) -> List[Citation]:
        """Identifiers found only in uploaded company documents."""
        return [c for c in self.citations if c.untrusted_only]

    @property
    def contested(self) -> List[Citation]:
        """Identifiers the corpus supports that an upload also discusses.

        Not an error on its own. A policy may quote a real rule correctly, so
        these are surfaced for a reviewer to compare rather than flagged.
        """
        return [c for c in self.citations if c.supported and c.also_in_company]

    @property
    def unverified_quotations(self) -> List[Quotation]:
        return [q for q in self.quotations if not q.supported]

    @property
    def escalation_required(self) -> bool:
        """True when a citation rests on a source that cannot support it."""
        return bool(self.untrusted_attributions)

    @property
    def total(self) -> int:
        return len(self.citations)

    @property
    def precision(self) -> Optional[float]:
        """Share of cited identifiers that were found in retrieved context.

        None when the answer cited nothing, which is different from citing
        nothing correctly.
        """
        if not self.citations:
            return None
        return round(len(self.supported) / len(self.citations), 4)

    def is_clean(self) -> bool:
        """True when every citation is supported and no abstention was required."""
        return not self.unsupported and not self.abstention_required

    def summary(self) -> Dict[str, object]:
        return {
            "total_citations": self.total,
            "supported": len(self.supported),
            "unsupported": len(self.unsupported),
            "citation_precision": self.precision,
            "abstention_required": self.abstention_required,
            "unsupported_identifiers": [c.text for c in self.unsupported],
            "escalation_required": self.escalation_required,
            "untrusted_attributions": [
                {"identifier": c.text, "source": c.source}
                for c in self.untrusted_attributions
            ],
            "contested_identifiers": [c.text for c in self.contested],
            "quotations_checked": len(self.quotations),
            "quotations_unverified": len(self.unverified_quotations),
        }


def _normalise(value: str) -> str:
    """Collapse whitespace, drop thousands separators, and lower-case."""
    cleaned = re.sub(r"\s+", " ", value).strip().lower()
    return cleaned.replace(",", "")


def extract_citations(text: str) -> List[Citation]:
    """Return every regulatory identifier and threshold found in text, deduplicated."""
    found: Dict[str, Citation] = {}
    claimed_spans: List[Tuple[int, int]] = []

    for kind, pattern in CITATION_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start, end = match.span()
            # Skip anything already captured by an earlier, more specific pattern.
            if any(s <= start < e or s < end <= e for s, e in claimed_spans):
                continue
            claimed_spans.append((start, end))

            raw = match.group(0)
            key = f"{kind}:{_normalise(raw)}"
            if key not in found:
                found[key] = Citation(
                    text=raw.strip(),
                    kind=kind,
                    normalised=_normalise(raw),
                )

    return list(found.values())


def _split_chunks(context: str) -> List[Tuple[str, str]]:
    """Split formatted RAG context into (source_name, chunk_text) pairs.

    Falls back to a single unattributed block when the context does not carry
    the chunk headers written by RAGPipeline._format_section.
    """
    headers = list(_CHUNK_HEADER.finditer(context))
    if not headers:
        return [("unattributed context", context)]

    chunks = []
    for i, header in enumerate(headers):
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(context)
        chunks.append((header.group(1).strip(), context[start:end]))
    return chunks


def _evidence_window(chunk: str, position: int, width: int = 120) -> str:
    """Return the text surrounding a match, for the record of where it came from."""
    start = max(0, position - width // 2)
    end = min(len(chunk), position + width // 2)
    snippet = re.sub(r"\s+", " ", chunk[start:end]).strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(chunk) else ""
    return f"{prefix}{snippet}{suffix}"


def requires_abstention(context: str) -> bool:
    """True when the retrieved context signals that there is nothing to rely on."""
    if not context or not context.strip():
        return True
    return any(marker.lower() in context.lower() for marker in _NO_EVIDENCE_MARKERS)


def _prepare(context: str) -> List[Tuple[str, str, str]]:
    """Split context into (source, original, normalised) triples for searching."""
    return [
        (source, text, _normalise(text)) for source, text in _split_chunks(context)
    ]


def _check_quotations(
    answer: str,
    regulatory_chunks: List[Tuple[str, str, str]],
    company_chunks: List[Tuple[str, str, str]],
) -> List["Quotation"]:
    """Check quoted passages against both sides and record which one matched.

    A quote from an uploaded policy is legitimate evidence of what that policy
    says. It is only the regulatory obligation that an upload cannot establish,
    so the trust level is recorded rather than used to reject the quote.
    """
    quotations = []
    seen = set()

    for match in _QUOTED_PASSAGE.finditer(answer):
        passage = match.group(1).strip()
        normalised = _normalise(passage)
        if normalised in seen:
            continue
        seen.add(normalised)

        quotation = Quotation(text=passage)
        for trust, chunks in (
            (TRUST_AUTHORITATIVE, regulatory_chunks),
            (TRUST_USER_SUPPLIED, company_chunks),
        ):
            for source, _, haystack in chunks:
                if normalised not in haystack:
                    continue
                quotation.supported = True
                quotation.trust = trust
                quotation.source = source
                break
            if quotation.supported:
                break

        quotations.append(quotation)

    return quotations


def validate(
    answer: str, regulatory_context: str, company_context: str = ""
) -> ValidationReport:
    """Check cited identifiers against the retrieved context.

    An identifier counts as supported only if it appears in the regulatory
    context. Finding it only in company context leaves it unsupported and
    sets escalation.
    """
    combined = f"{regulatory_context}\n\n{company_context}".strip()
    report = ValidationReport(abstention_required=requires_abstention(combined))
    report.citations = extract_citations(answer)

    regulatory_chunks = _prepare(regulatory_context) if regulatory_context else []
    company_chunks = _prepare(company_context) if company_context else []

    report.quotations = _check_quotations(answer, regulatory_chunks, company_chunks)

    if not report.citations:
        return report

    for citation in report.citations:
        for source, original, haystack in regulatory_chunks:
            position = haystack.find(citation.normalised)
            if position == -1:
                continue
            citation.supported = True
            citation.trust = TRUST_AUTHORITATIVE
            citation.source = source
            citation.evidence = _evidence_window(original, position)
            break

        company_hit = next(
            (
                source
                for source, _, haystack in company_chunks
                if haystack.find(citation.normalised) != -1
            ),
            None,
        )

        if citation.supported:
            # Both sides mention it. Flag the overlap so someone checks the
            # upload is not quoting the rule with different numbers.
            citation.also_in_company = company_hit is not None
            citation.company_source = company_hit
            continue

        if company_hit is None:
            continue

        # Still record the source, so the reviewer can see what claimed it.
        for source, original, haystack in company_chunks:
            position = haystack.find(citation.normalised)
            if position == -1:
                continue
            citation.untrusted_only = True
            citation.trust = TRUST_USER_SUPPLIED
            citation.source = source
            citation.evidence = _evidence_window(original, position)
            break

    return report


def annotate(answer: str, report: ValidationReport) -> str:
    """Mark unsupported identifiers inline so a reviewer can see them at a glance.

    Flagging rather than deletion: removing text would hide the failure, and the
    point of the check is that unsupported claims become visible.
    """
    if not report.unsupported:
        return answer

    annotated = answer
    for citation in report.unsupported:
        annotated = re.sub(
            r"(?<!\[UNVERIFIED: )" + re.escape(citation.text) + r"\b",
            f"[UNVERIFIED: {citation.text}]",
            annotated,
            flags=re.IGNORECASE,
        )
    return annotated


def format_report(report: ValidationReport) -> str:
    """Render a Markdown section describing the validation outcome."""
    lines = ["", "---", "", "## Citation Validation", ""]

    if report.abstention_required:
        lines.append(
            "**Insufficient evidence.** The retrieval step returned no usable "
            "regulatory or company context, so any specific finding in this "
            "report is unsupported and the system should abstain."
        )
        lines.append("")

    if report.total == 0:
        lines.append("No regulatory identifiers were cited, so none could be checked.")
        lines.extend(_quotation_lines(report))
        return "\n".join(lines)

    precision = report.precision
    lines.append(
        f"Checked {report.total} cited identifier(s) against the retrieved context: "
        f"{len(report.supported)} supported, {len(report.unsupported)} unsupported "
        f"(citation precision {precision:.2f})."
    )
    lines.append("")

    if report.escalation_required:
        lines.append(
            "**Escalation required: unauthenticated regulatory attribution.** "
            "The identifier(s) below appear only in uploaded company documents, "
            "not in the regulatory corpus. An uploaded document cannot establish "
            "a regulatory obligation, so these must be confirmed against the "
            "authoritative instrument before any finding relies on them."
        )
        lines.append("")
        for citation in report.untrusted_attributions:
            lines.append(
                f"- `{citation.text}` ({citation.kind}) asserted by "
                f"*{citation.source}* (user-supplied)"
            )
        lines.append("")

    absent = [c for c in report.unsupported if not c.untrusted_only]
    if absent:
        lines.append("Identifiers not found in any retrieved chunk:")
        lines.append("")
        for citation in absent:
            lines.append(f"- `{citation.text}` ({citation.kind})")
        lines.append("")
        lines.append(
            "These were produced from model memory rather than retrieved evidence "
            "and must be verified against the authoritative source before use."
        )
    elif not report.unsupported:
        lines.append(
            "Every cited identifier was located in the regulatory context."
        )

    if report.contested:
        lines.append("")
        lines.append(
            "Also discussed in an uploaded document. Check the upload does not "
            "restate these with different figures:"
        )
        lines.append("")
        for citation in report.contested:
            lines.append(
                f"- `{citation.text}` in {citation.source}, also in "
                f"{citation.company_source}"
            )

    lines.extend(_quotation_lines(report))

    return "\n".join(lines)


def _quotation_lines(report: ValidationReport) -> List[str]:
    """Render the quoted-passage check, if the answer quoted anything."""
    if not report.quotations:
        return []

    lines = ["", "### Quoted passages", ""]
    for quotation in report.quotations:
        excerpt = quotation.text if len(quotation.text) <= 90 else (
            quotation.text[:90] + "..."
        )
        if quotation.supported:
            lines.append(f'- "{excerpt}" found in {quotation.source}')
        else:
            lines.append(f'- "{excerpt}" not found in any retrieved chunk')

    if report.unverified_quotations:
        lines.append("")
        lines.append(
            "Unmatched quotations may be paraphrases rather than fabrications, "
            "but they were not located verbatim and should be checked."
        )
    return lines
