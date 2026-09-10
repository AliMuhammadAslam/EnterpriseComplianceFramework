"""Evidence traces recording how each analysis was produced.

The execution steps shown to a user are generated text describing what the
system reports doing, so they cannot serve as an audit record. A trace holds
the checkable parts instead: request, model settings, retrieved chunks, plan,
tool calls, validation result, answer, and any human override.

Chunks are stored as hashes plus a short redacted preview rather than in full,
so a reviewer can confirm which chunk was used without a second copy of the
company's policy text.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Redacted before anything is written to disk. Order matters: a CNIC is
# thirteen digits and would be mislabelled as a card number if card ran first.
# The patterns stay narrow because over-redaction would eat the clause
# numbering these traces exist to preserve.
REDACTION_PATTERNS = [
    ("cnic", re.compile(r"\b\d{5}-\d{7}-\d\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("phone", re.compile(r"(?:\+92|0092|\b03)\d[\d -]{7,12}\b")),
    ("iban", re.compile(r"\bPK\d{2}[A-Z]{4}\d{16}\b", re.IGNORECASE)),
    ("card", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}\b")),
    ("api_key", re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b")),
]

PREVIEW_CHARS = 160


def redact(text: str) -> str:
    """Replace sensitive identifiers with a typed placeholder."""
    if not text:
        return text
    cleaned = text
    for label, pattern in REDACTION_PATTERNS:
        cleaned = pattern.sub(f"[REDACTED:{label}]", cleaned)
    return cleaned


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class RetrievedChunk(BaseModel):
    """One chunk that entered the prompt, identified rather than duplicated."""

    source: str = ""
    section: str = ""
    relevance: float = 0.0
    content_sha256: str = ""
    preview: str = ""

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> "RetrievedChunk":
        content = result.get("content", "")
        metadata = result.get("metadata", {}) or {}
        return cls(
            source=metadata.get("source", "unknown"),
            section=metadata.get("section", ""),
            relevance=round(float(result.get("relevance_score", 0.0)), 4),
            content_sha256=_sha256(content),
            preview=redact(content)[:PREVIEW_CHARS],
        )


class ToolCall(BaseModel):
    """A single operation the pipeline performed on the way to an answer."""

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    outcome: str = ""
    succeeded: bool = True


class HumanOverride(BaseModel):
    """A reviewer's correction to a system conclusion."""

    reviewer: str
    at: str
    field: str
    original: str
    replacement: str
    reason: str = ""


class EvidenceTrace(BaseModel):
    """Everything needed to reconstruct and assess one compliance analysis."""

    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    recorded_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    user_id: str = "system"
    request: str = ""
    intent: str = ""
    model_configuration: Dict[str, Any] = Field(default_factory=dict)
    retrieved_chunks: List[RetrievedChunk] = Field(default_factory=list)
    plan: Optional[Dict[str, Any]] = None
    tool_calls: List[ToolCall] = Field(default_factory=list)
    validation: Optional[Dict[str, Any]] = None
    final_answer: str = ""
    human_overrides: List[HumanOverride] = Field(default_factory=list)

    def add_override(
        self, reviewer: str, field_name: str, original: str, replacement: str, reason: str = ""
    ) -> "EvidenceTrace":
        """Record a reviewer correction without discarding what the system said."""
        self.human_overrides.append(
            HumanOverride(
                reviewer=reviewer,
                at=datetime.now(timezone.utc).isoformat(),
                field=field_name,
                original=redact(original),
                replacement=redact(replacement),
                reason=reason,
            )
        )
        return self


class EvidenceTraceStore:
    """Writes evidence traces to disk, one JSON file per analysis."""

    def __init__(self, trace_dir: str = None):
        self.trace_dir = trace_dir or os.getenv("EVIDENCE_TRACE_DIR", "./evidence_traces")
        os.makedirs(self.trace_dir, exist_ok=True)

    def build(
        self,
        request: str,
        user_id: str = "system",
        intent: str = "",
        model_configuration: Optional[Dict[str, Any]] = None,
        retrieved: Optional[List[Dict[str, Any]]] = None,
        plan: Optional[Any] = None,
        tool_calls: Optional[List[ToolCall]] = None,
        validation: Optional[Dict[str, Any]] = None,
        final_answer: str = "",
    ) -> EvidenceTrace:
        """Assemble a trace, redacting the request and answer as they go in."""
        return EvidenceTrace(
            user_id=user_id,
            request=redact(request),
            intent=intent,
            model_configuration=model_configuration or {},
            retrieved_chunks=[
                RetrievedChunk.from_result(r) for r in (retrieved or [])
            ],
            plan=_plan_to_dict(plan),
            tool_calls=tool_calls or [],
            validation=validation,
            final_answer=redact(final_answer),
        )

    def save(self, trace: EvidenceTrace) -> str:
        """Persist a trace and return its path."""
        path = os.path.join(self.trace_dir, f"trace_{trace.trace_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(trace.model_dump_json(indent=2))
        return path

    def load(self, trace_id: str) -> Optional[EvidenceTrace]:
        """Read back a stored trace, or None if it does not exist."""
        path = os.path.join(self.trace_dir, f"trace_{trace_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return EvidenceTrace(**json.load(f))


def _plan_to_dict(plan: Any) -> Optional[Dict[str, Any]]:
    """Normalise a Plan model, dict, or None into a plain dict."""
    if plan is None:
        return None
    if isinstance(plan, dict):
        return plan
    if hasattr(plan, "model_dump"):
        return plan.model_dump()
    return {"goal": str(plan)}
