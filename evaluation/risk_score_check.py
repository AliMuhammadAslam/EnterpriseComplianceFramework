"""Deterministic check of the Regulatory Risk Score table in a generated report.

The prompt defines the score, the priority bands and the escalation rule, but
the model fills the table in. Across 40 sampled rows the arithmetic and bands
were right, yet 16 rows were marked "escalated" where escalation changed
nothing: the model tags every severity-5 gap, which tells a reader the formula
was overridden when it was not. Each row is recomputed with the same rule the
sensitivity analysis uses, and any cell that disagrees is corrected and listed,
so a correction is visible rather than silent.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from evaluation.risk_sensitivity import IMMEDIATE, LONG, MEDIUM, final_band

SECTION_HEADING = "Regulatory Risk Score and Prioritization"
BANDS = [IMMEDIATE, MEDIUM, LONG]

# "(escalated)" on its own, or "escalated" as one item inside other wording.
_ESCALATED_BRACKETED = re.compile(r"\s*\(\s*escalated\s*\)", re.IGNORECASE)
_ESCALATED_ITEM = re.compile(r"[\s,;]*\bescalated\b", re.IGNORECASE)


@dataclass
class RiskScoreCheck:
    rows_checked: int = 0
    corrections: List[str] = field(default_factory=list)
    unparsed: List[str] = field(default_factory=list)
    table_found: bool = False


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row(cells: List[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _band_in(cell: str) -> Optional[str]:
    lowered = cell.lower()
    return next((band for band in BANDS if band.lower() in lowered), None)


def _fixed_band_cell(cell: str, band: str, escalated: bool) -> str:
    """Correct the band and the escalation marker, keeping any other wording."""
    current = _band_in(cell)
    text = cell
    if current != band:
        text = band
    has_marker = bool(re.search(r"escalated", text, re.IGNORECASE))
    if has_marker and not escalated:
        text = _ESCALATED_BRACKETED.sub("", text)
        text = _ESCALATED_ITEM.sub("", text).strip(" ,;")
    elif escalated and not has_marker:
        text = f"{text} (escalated)"
    return text


def check_and_correct(report: str) -> Tuple[str, RiskScoreCheck]:
    """Return the report with the scoring table corrected, and what was changed."""
    result = RiskScoreCheck()
    start = report.find(SECTION_HEADING)
    if start == -1:
        return report, result

    lines = report.split("\n")
    offset = report[:start].count("\n")
    header_index = None
    for i in range(offset, len(lines)):
        if i > offset and lines[i].startswith("## "):
            break
        if lines[i].strip().startswith("|"):
            header_index = i
            break
    if header_index is None:
        return report, result

    header = [c.lower() for c in _cells(lines[header_index])]
    try:
        col = {name: header.index(name) for name in ("s", "l", "g")}
        col["score"] = next(i for i, h in enumerate(header) if "score" in h)
        col["band"] = next(i for i, h in enumerate(header) if "band" in h or "priority" in h)
    except (ValueError, StopIteration):
        return report, result
    gap_col = 0
    result.table_found = True

    i = header_index + 2  # skip the separator row
    while i < len(lines) and lines[i].strip().startswith("|"):
        cells = _cells(lines[i])
        if len(cells) != len(header):
            result.unparsed.append(lines[i].strip())
            i += 1
            continue
        try:
            s, l, g = (int(cells[col[k]]) for k in ("s", "l", "g"))
            shown_score = int(re.sub(r"[^\d]", "", cells[col["score"]]))
        except ValueError:
            result.unparsed.append(lines[i].strip())
            i += 1
            continue

        result.rows_checked += 1
        score, band, escalated = final_band(s, l, g)
        name = cells[gap_col] or f"row {result.rows_checked}"
        changes = []

        if shown_score != score:
            changes.append(f"score {shown_score} corrected to {score} ({s} x {l} x {g})")
            cells[col["score"]] = str(score)

        band_cell = cells[col["band"]]
        fixed = _fixed_band_cell(band_cell, band, escalated)
        if fixed != band_cell:
            if _band_in(band_cell) != band:
                changes.append(f"band '{band_cell}' corrected to '{fixed}'")
            elif escalated:
                changes.append("escalation marker added: the severity rule moved this band")
            else:
                changes.append(
                    f"'escalated' removed: a score of {score} is already {band}, "
                    "so the escalation rule changed nothing"
                )
            cells[col["band"]] = fixed

        if changes:
            lines[i] = _row(cells)
            result.corrections.append(f"{name}: {'; '.join(changes)}")
        i += 1

    return "\n".join(lines), result


def format_check(result: RiskScoreCheck) -> str:
    """Markdown section describing the outcome, or nothing if there was no table."""
    if not result.table_found:
        return ""
    lines = ["", "---", "", "## Risk Score Check", ""]
    if result.corrections:
        lines.append(
            f"Recomputed {result.rows_checked} row(s) from their S, L and G values. "
            f"{len(result.corrections)} row(s) disagreed with the scoring rule and were "
            "corrected in the table above:"
        )
        lines.append("")
        lines.extend(f"- {c}" for c in result.corrections)
    else:
        lines.append(
            f"Recomputed {result.rows_checked} row(s) from their S, L and G values; "
            "every score, band and escalation marker matches the scoring rule."
        )
    if result.unparsed:
        lines.append("")
        lines.append(f"{len(result.unparsed)} row(s) could not be read and were not checked.")
    return "\n".join(lines)
