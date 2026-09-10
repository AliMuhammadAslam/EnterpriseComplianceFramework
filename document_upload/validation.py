"""Checks applied to uploaded files before they are parsed or stored.

An uploaded document is untrusted input that ends up inside a prompt, so the
extension alone is not enough to decide what a file is or what it may contain.
"""

import os
import re
from typing import Dict, List, Tuple

from dotenv import load_dotenv

load_dotenv()

# Leading bytes each format must start with. TXT has no signature, so it is
# checked by decoding instead.
FILE_SIGNATURES = {
    "pdf": [b"%PDF-"],
    "docx": [b"PK\x03\x04"],
}

MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "500"))
MAX_DOCX_PARAGRAPHS = int(os.getenv("MAX_DOCX_PARAGRAPHS", "20000"))
MAX_EXTRACTED_CHARS = int(os.getenv("MAX_EXTRACTED_CHARS", "2000000"))
MAX_FILENAME_LENGTH = 120

# Phrases that try to talk to the model rather than describe a policy. Narrow
# on purpose: a real compliance document should not contain any of these, and
# over-matching would corrupt the customer's own text.
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|preceding)\s+instructions?", re.I),
    re.compile(r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above|preceding)\s+instructions?", re.I),
    re.compile(r"forget\s+(?:everything|all)\s+(?:you|above|before)[\w\s]{0,20}", re.I),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\s+[\w\s]{0,30}", re.I),
    re.compile(r"new\s+(?:system\s+)?instructions?\s*:", re.I),
    re.compile(r"system\s+prompt\s*:", re.I),
    re.compile(r"</?(?:system|assistant|user)>", re.I),
    re.compile(r"mark\s+(?:this|the)\s+(?:company|organisation|organization)?\s*as\s+fully\s+compliant", re.I),
]

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._\- ]")
_REPEATED_DOTS = re.compile(r"\.{2,}")


class UploadRejected(ValueError):
    """Raised when a file fails validation."""


def safe_filename(original: str, fallback: str = "document") -> str:
    """Reduce a filename to something safe to join onto a directory path.

    Directory components are discarded rather than escaped, so a crafted name
    cannot walk out of the user's upload folder.
    """
    name = (original or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE_NAME_CHARS.sub("_", name)
    name = _REPEATED_DOTS.sub(".", name).strip(". ")

    if not name:
        name = fallback

    stem, dot, ext = name.rpartition(".")
    if dot:
        stem = stem[:MAX_FILENAME_LENGTH] or fallback
        name = f"{stem}.{ext[:10]}"
    else:
        name = name[:MAX_FILENAME_LENGTH]

    return name


def verify_file_signature(file_path: str, ext: str) -> None:
    """Confirm the file's leading bytes match the extension it claims."""
    expected = FILE_SIGNATURES.get(ext)

    if expected is None:
        _verify_is_text(file_path)
        return

    with open(file_path, "rb") as f:
        head = f.read(8)

    if not any(head.startswith(sig) for sig in expected):
        raise UploadRejected(
            f"File contents do not match a .{ext} file. "
            "The extension may have been changed."
        )


def _verify_is_text(file_path: str) -> None:
    """Reject a binary file that has been renamed to .txt."""
    with open(file_path, "rb") as f:
        sample = f.read(4096)

    if b"\x00" in sample:
        raise UploadRejected("File contents do not match a .txt file.")

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
        except UnicodeDecodeError:
            raise UploadRejected("File is not readable as text.")


def check_document_limits(file_path: str, ext: str) -> Dict[str, int]:
    """Reject documents whose size would make parsing expensive.

    Checked before extraction so a small file that expands enormously is
    stopped early rather than after the work is done.
    """
    if ext == "pdf":
        try:
            from PyPDF2 import PdfReader

            pages = len(PdfReader(file_path).pages)
        except UploadRejected:
            raise
        except Exception as e:
            raise UploadRejected(f"PDF could not be read: {e}")

        if pages > MAX_PDF_PAGES:
            raise UploadRejected(
                f"PDF has {pages} pages, the limit is {MAX_PDF_PAGES}."
            )
        return {"pages": pages}

    if ext == "docx":
        try:
            from docx import Document

            paragraphs = len(Document(file_path).paragraphs)
        except UploadRejected:
            raise
        except Exception as e:
            raise UploadRejected(f"DOCX could not be read: {e}")

        if paragraphs > MAX_DOCX_PARAGRAPHS:
            raise UploadRejected(
                f"Document has {paragraphs} paragraphs, "
                f"the limit is {MAX_DOCX_PARAGRAPHS}."
            )
        return {"paragraphs": paragraphs}

    return {}


def neutralise_instructions(text: str) -> Tuple[str, List[str]]:
    """Defang text in a document that addresses the model rather than the reader.

    Matches are marked, not deleted. Removing content silently would hide part
    of the customer's own document from an analysis meant to assess it.
    """
    found = []

    def mark(match):
        found.append(match.group(0))
        return f"[neutralised instruction: {match.group(0)}]"

    cleaned = text
    for pattern in INJECTION_PATTERNS:
        cleaned = pattern.sub(mark, cleaned)

    return cleaned, found


def check_extracted_size(text: str) -> None:
    """Reject extracted text large enough to be a decompression bomb."""
    if len(text) > MAX_EXTRACTED_CHARS:
        raise UploadRejected(
            f"Extracted text is {len(text)} characters, "
            f"the limit is {MAX_EXTRACTED_CHARS}."
        )
