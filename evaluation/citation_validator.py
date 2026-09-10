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

Scope: this checks that a cited identifier exists in an authorised chunk and
records where it was found. It does not judge whether the cited provision
semantically entails the conclusion drawn from it; that remains open.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Ordered longest-first so that a more specific pattern wins where two overlap.
CITATION_PATTERNS: List[Tuple[str, str]] = [
    ("iso_control", r"\bA\.\d+\.\d+\b"),
    ("requirement", r"\bRequirement\s+\d+(?:\.\d+)*\b"),
    ("article", r"\bArticle\s+\d+(?:\(\d+\))?\b"),
    ("section", r"\bSection\s+\d+(?:\(\d+\))?\b"),
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


@dataclass
class Citation:
    """A single regulatory identifier found in a generated answer."""

    text: str
    kind: str
    normalised: str
    supported: bool = False
    source: Optional[str] = None
    evidence: Optional[str] = None


@dataclass
class ValidationReport:
    """Outcome of checking every citation in one answer."""

    citations: List[Citation] = field(default_factory=list)
    abstention_required: bool = False

    @property
    def supported(self) -> List[Citation]:
        return [c for c in self.citations if c.supported]

    @property
    def unsupported(self) -> List[Citation]:
        return [c for c in self.citations if not c.supported]

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


def validate(answer: str, context: str) -> ValidationReport:
    """Check every identifier cited in answer against the retrieved context."""
    report = ValidationReport(abstention_required=requires_abstention(context))
    report.citations = extract_citations(answer)

    if not report.citations:
        return report

    chunks = _split_chunks(context)
    normalised_chunks = [(source, text, _normalise(text)) for source, text in chunks]

    for citation in report.citations:
        for source, original, haystack in normalised_chunks:
            position = haystack.find(citation.normalised)
            if position == -1:
                continue
            citation.supported = True
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
        return "\n".join(lines)

    precision = report.precision
    lines.append(
        f"Checked {report.total} cited identifier(s) against the retrieved context: "
        f"{len(report.supported)} supported, {len(report.unsupported)} unsupported "
        f"(citation precision {precision:.2f})."
    )
    lines.append("")

    if report.unsupported:
        lines.append("Identifiers not found in any retrieved chunk:")
        lines.append("")
        for citation in report.unsupported:
            lines.append(f"- `{citation.text}` ({citation.kind})")
        lines.append("")
        lines.append(
            "These were produced from model memory rather than retrieved evidence "
            "and must be verified against the authoritative source before use."
        )
    else:
        lines.append("Every cited identifier was located in the retrieved context.")

    return "\n".join(lines)
