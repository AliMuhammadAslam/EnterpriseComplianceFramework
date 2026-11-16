"""Dashboard data read from saved evaluation reports.

Every figure comes from two tables each report already contains:
"Standards Coverage" (Standard | Status | Note) and "Regulatory Risk Score and
Prioritization" (Gap | Standard | S | L | G | Risk Score | Priority Band). The
risk table is the version corrected by risk_score_check before the report is
saved. Rows that cannot be read are counted, not guessed.
"""

import re
from typing import Any, Dict, List, Optional

from evaluation.risk_score_check import BANDS, SECTION_HEADING, _band_in, _cells

COVERAGE_HEADING = "Standards Coverage"
COVERAGE_STATUSES = ["Findings", "Documentation gap", "Not applicable"]

# Valid factor ranges for the Regulatory Risk Score (Severity x Likelihood x
# Regulatory Gravity), as defined in the evaluation prompt.
S_RANGE, L_RANGE, G_RANGE = range(1, 6), range(1, 4), range(1, 4)
_SEPARATOR = re.compile(r"^\|?\s*:?-{2,}")


def _plain(cell: str) -> str:
    """Cell text without Markdown emphasis or surrounding whitespace."""
    return re.sub(r"[*_`]", "", cell).strip()


def _table_after(text: str, heading: str) -> Optional[Dict[str, Any]]:
    """The first Markdown table under a level-2 heading, or None.

    Returns the lower-cased header cells and the data rows as cell lists.
    """
    lines = text.split("\n")
    start = next(
        (i for i, line in enumerate(lines)
         if line.startswith("## ") and line[3:].strip().lower().startswith(heading.lower())),
        None,
    )
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## "):
            return None
        if line.startswith("|"):
            header = [_plain(c).lower() for c in _cells(line)]
            rows = []
            j = i + 1
            if j < len(lines) and _SEPARATOR.match(lines[j].strip()):
                j += 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append([_plain(c) for c in _cells(lines[j])])
                j += 1
            return {"header": header, "rows": rows}
    return None


def _column(header: List[str], *names: str) -> Optional[int]:
    """Index of the first header cell equal to, or containing, one of the names."""
    for name in names:
        if name in header:
            return header.index(name)
    for name in names:
        for i, cell in enumerate(header):
            if name in cell:
                return i
    return None


def _factor_column(header: List[str], letter: str, word: str) -> Optional[int]:
    """Column of a risk factor, headed "S", "Severity", "Severity (S)" and so on."""
    for i, cell in enumerate(header):
        if cell == letter or cell.endswith(f"({letter})") or word in cell:
            return i
    return None


def _status(cell: str) -> str:
    lowered = cell.lower()
    if "documentation gap" in lowered:
        return "Documentation gap"
    if "not applicable" in lowered:
        return "Not applicable"
    if "finding" in lowered:
        return "Findings"
    return "Unrecognised"


def parse_coverage(text: str) -> Dict[str, Any]:
    """Standards and their coverage status from the Standards Coverage table."""
    table = _table_after(text, COVERAGE_HEADING)
    if not table:
        return {"found": False, "rows": [], "unparsed": 0}
    std_col = _column(table["header"], "standard")
    status_col = _column(table["header"], "status")
    if std_col is None or status_col is None:
        return {"found": False, "rows": [], "unparsed": len(table["rows"])}
    rows, unparsed = [], 0
    for cells in table["rows"]:
        if len(cells) != len(table["header"]) or not cells[std_col]:
            unparsed += 1
            continue
        status = _status(cells[status_col])
        if status == "Unrecognised":
            unparsed += 1
            continue
        rows.append({"standard": cells[std_col], "status": status})
    return {"found": True, "rows": rows, "unparsed": unparsed}


def parse_risks(text: str) -> Dict[str, Any]:
    """Scored gaps from the Regulatory Risk Score and Prioritization table."""
    table = _table_after(text, SECTION_HEADING)
    if not table:
        return {"found": False, "rows": [], "unparsed": 0}
    header = table["header"]
    col = {
        "gap": _column(header, "gap"),
        "standard": _column(header, "standard"),
        "s": _factor_column(header, "s", "severity"),
        "l": _factor_column(header, "l", "likelihood"),
        "g": _factor_column(header, "g", "gravity"),
        "band": _column(header, "priority band", "band", "priority"),
    }
    if any(v is None for v in col.values()):
        return {"found": False, "rows": [], "unparsed": len(table["rows"])}
    rows, unparsed = [], 0
    for cells in table["rows"]:
        if len(cells) != len(header):
            unparsed += 1
            continue
        try:
            s, l, g = (int(cells[col[k]]) for k in ("s", "l", "g"))
        except ValueError:
            unparsed += 1
            continue
        if s not in S_RANGE or l not in L_RANGE or g not in G_RANGE:
            unparsed += 1
            continue
        # The score is defined as S x L x G; the saved table has already been
        # corrected to it, so computing it avoids misreading a cell like "24.0".
        score = s * l * g
        band = _band_in(cells[col["band"]])
        if band is None:
            unparsed += 1
            continue
        rows.append({
            "gap": cells[col["gap"]],
            "standard": cells[col["standard"]],
            "s": s, "l": l, "g": g,
            "score": score,
            "band": band,
            "escalated": "escalated" in cells[col["band"]].lower(),
        })
    return {"found": True, "rows": rows, "unparsed": unparsed}


def summarise_report(record: Dict[str, Any]) -> Dict[str, Any]:
    """Dashboard figures for one saved report."""
    text = record.get("report_text", "") or ""
    coverage = parse_coverage(text)
    risks = parse_risks(text)
    return {
        "report_id": record.get("report_id"),
        "timestamp": record.get("timestamp"),
        "standards": record.get("standards", []),
        "coverage": coverage["rows"],
        "coverage_found": coverage["found"],
        "gaps": risks["rows"],
        "risk_table_found": risks["found"],
        "unparsed_rows": coverage["unparsed"] + risks["unparsed"],
    }


def build_dashboard(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-report dashboard figures, oldest first."""
    reports = [summarise_report(r) for r in records]
    reports.sort(key=lambda r: r["timestamp"] or "")
    return {
        "reports": reports,
        "bands": list(BANDS),
        "coverage_statuses": list(COVERAGE_STATUSES),
    }
