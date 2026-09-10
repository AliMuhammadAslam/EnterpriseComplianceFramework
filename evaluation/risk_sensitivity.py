"""Sensitivity analysis for the Regulatory Risk Score.

Score = Obligation Severity (S, 1-5) x Likelihood (L, 1-3) x Adequacy Gap (G, 1-3),
banded at 24 and 10, with an escalation rule for severity 5.

The whole input space is only 45 combinations, so this enumerates it exactly
rather than sampling. No API calls.

Run with:  python -m evaluation.risk_sensitivity
"""

import os
import sys
from itertools import product
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMMEDIATE = "Immediate"
MEDIUM = "Medium-term"
LONG = "Long-term"

DEFAULT_IMMEDIATE_CUT = 24
DEFAULT_MEDIUM_CUT = 10

S_RANGE = range(1, 6)
L_RANGE = range(1, 4)
G_RANGE = range(1, 4)

# What each severity level means, from the scoring prompt in engine.py.
SEVERITY_MEANING = {
    5: "AML/CFT, sanctions, financial crime, customer data protection",
    4: "core security controls (access control, encryption, incident response)",
    3: "governance and operational resilience",
    2: "reporting and record keeping",
    1: "administrative or procedural",
}


def raw_band(score: int, immediate_cut: int, medium_cut: int) -> str:
    """Band from the multiplicative score alone, before escalation."""
    if score >= immediate_cut:
        return IMMEDIATE
    if score >= medium_cut:
        return MEDIUM
    return LONG


def final_band(s: int, l: int, g: int, immediate_cut: int = DEFAULT_IMMEDIATE_CUT,
               medium_cut: int = DEFAULT_MEDIUM_CUT) -> Tuple[int, str, bool]:
    """Return the score, the band actually assigned, and whether escalation moved it."""
    score = s * l * g
    band = raw_band(score, immediate_cut, medium_cut)

    escalated = False
    if s == 5:
        if g == 3 and band != IMMEDIATE:
            band, escalated = IMMEDIATE, True
        elif band == LONG:
            band, escalated = MEDIUM, True

    return score, band, escalated


def enumerate_space(immediate_cut: int = DEFAULT_IMMEDIATE_CUT,
                    medium_cut: int = DEFAULT_MEDIUM_CUT) -> List[Dict]:
    """Every S, L, G combination with its score and band."""
    rows = []
    for s, l, g in product(S_RANGE, L_RANGE, G_RANGE):
        score, band, escalated = final_band(s, l, g, immediate_cut, medium_cut)
        rows.append({
            "S": s, "L": l, "G": g,
            "score": score,
            "raw_band": raw_band(score, immediate_cut, medium_cut),
            "band": band,
            "escalated": escalated,
        })
    return rows


def band_counts(rows: List[Dict]) -> Dict[str, int]:
    counts = {IMMEDIATE: 0, MEDIUM: 0, LONG: 0}
    for r in rows:
        counts[r["band"]] += 1
    return counts


def achievable_scores() -> List[int]:
    """The distinct products the formula can actually produce."""
    return sorted({s * l * g for s, l, g in product(S_RANGE, L_RANGE, G_RANGE)})


def threshold_sweep() -> List[Dict]:
    """Band distribution as the two cut points move.

    Shows whether the chosen thresholds sit on a stable plateau or on a cliff.
    """
    results = []
    for immediate_cut in range(15, 37):
        rows = enumerate_space(immediate_cut, DEFAULT_MEDIUM_CUT)
        counts = band_counts(rows)
        results.append({
            "varied": "immediate",
            "cut": immediate_cut,
            "immediate": counts[IMMEDIATE],
            "medium": counts[MEDIUM],
            "long": counts[LONG],
        })
    for medium_cut in range(4, 16):
        rows = enumerate_space(DEFAULT_IMMEDIATE_CUT, medium_cut)
        counts = band_counts(rows)
        results.append({
            "varied": "medium",
            "cut": medium_cut,
            "immediate": counts[IMMEDIATE],
            "medium": counts[MEDIUM],
            "long": counts[LONG],
        })
    return results


def stability(rows_default: List[Dict], varied_cut: int, which: str) -> int:
    """How many of the 45 combinations change band when one cut point moves by one."""
    if which == "immediate":
        rows = enumerate_space(varied_cut, DEFAULT_MEDIUM_CUT)
    else:
        rows = enumerate_space(DEFAULT_IMMEDIATE_CUT, varied_cut)
    return sum(1 for a, b in zip(rows_default, rows) if a["band"] != b["band"])


WORKED_EXAMPLES = [
    {
        "gap": "No documented customer due diligence procedure",
        "standard": "SBP AML/CFT Regulations",
        "S": 5, "L": 3, "G": 3,
        "note": "Severe obligation, active regulator focus, control entirely absent.",
    },
    {
        "gap": "CDD procedure exists but omits enhanced due diligence for high risk customers",
        "standard": "SBP AML/CFT Regulations",
        "S": 5, "L": 3, "G": 2,
        "note": "Same obligation, partially present rather than absent.",
    },
    {
        "gap": "Customer data retention schedule undocumented",
        "standard": "SBP Data Localisation",
        "S": 5, "L": 1, "G": 1,
        "note": "The case the escalation rule exists for: severe obligation, "
                "low enforcement likelihood, minor gap. Scores 5, which the raw "
                "formula would place in Long-term.",
    },
    {
        "gap": "Encryption at rest not applied to backup media",
        "standard": "ISO 27001 A.8.24",
        "S": 4, "L": 2, "G": 3,
        "note": "Core security control, moderate enforcement focus, absent.",
    },
    {
        "gap": "Access review records incomplete for one quarter",
        "standard": "ISO 27001 A.5.18",
        "S": 4, "L": 2, "G": 1,
        "note": "Same control family, minor gap.",
    },
    {
        "gap": "Business continuity plan not version controlled",
        "standard": "ISO 22301",
        "S": 3, "L": 1, "G": 2,
        "note": "Governance item, low enforcement focus.",
    },
    {
        "gap": "Incident log missing reviewer initials",
        "standard": "Internal policy",
        "S": 1, "L": 1, "G": 1,
        "note": "Floor of the scale.",
    },
]


def _fmt_table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def build_report() -> str:
    rows = enumerate_space()
    counts = band_counts(rows)
    total = len(rows)
    escalated = [r for r in rows if r["escalated"]]
    scores = achievable_scores()

    parts = ["# Regulatory Risk Score: sensitivity analysis", ""]
    parts.append(
        f"The score is S x L x G with S in 1-5 and L, G in 1-3, giving "
        f"{total} possible combinations and {len(scores)} distinct scores. "
        "The space is small enough to enumerate exactly, so what follows is "
        "complete rather than sampled."
    )
    parts.append("")

    parts.append("## Band distribution")
    parts.append("")
    parts.append(_fmt_table(
        ["Band", "Combinations", "Share"],
        [[b, counts[b], f"{counts[b] / total:.0%}"] for b in (IMMEDIATE, MEDIUM, LONG)],
    ))
    parts.append("")

    parts.append("## Effect of the escalation rule")
    parts.append("")
    parts.append(
        f"Escalation changes the band for {len(escalated)} of {total} combinations "
        f"({len(escalated) / total:.0%}). All of them have S = 5, which is the "
        "intended scope of the rule."
    )
    parts.append("")
    parts.append(_fmt_table(
        ["S", "L", "G", "Score", "Band from score alone", "Band assigned"],
        [[r["S"], r["L"], r["G"], r["score"], r["raw_band"], r["band"]] for r in escalated],
    ))
    parts.append("")

    parts.append("## Achievable scores")
    parts.append("")
    parts.append(
        "The formula cannot produce every integer. The distinct achievable "
        f"scores are: {', '.join(str(s) for s in scores)}."
    )
    gaps_near_24 = [s for s in scores if 20 <= s <= 30]
    parts.append("")
    parts.append(
        f"Near the Immediate cut point of 24 the achievable scores are "
        f"{', '.join(str(s) for s in gaps_near_24)}. "
        "This matters for interpreting the threshold: a cut point placed anywhere "
        "in a gap between achievable scores classifies identically, so the exact "
        "number carries less weight than it appears to."
    )
    parts.append("")

    parts.append("## Moving the thresholds")
    parts.append("")
    parts.append(
        "Each cut point was moved across its plausible range while the other was "
        "held fixed. The table reports how many of the 45 combinations fall in "
        "each band."
    )
    parts.append("")

    sweep = threshold_sweep()
    for which, label, default in (("immediate", "Immediate cut point", DEFAULT_IMMEDIATE_CUT),
                                  ("medium", "Medium-term cut point", DEFAULT_MEDIUM_CUT)):
        subset = [s for s in sweep if s["varied"] == which]
        parts.append(f"### {label} (default {default})")
        parts.append("")
        parts.append(_fmt_table(
            ["Cut", "Immediate", "Medium-term", "Long-term", "Changed vs default"],
            [[s["cut"], s["immediate"], s["medium"], s["long"],
              stability(rows, s["cut"], which)] for s in subset],
        ))
        parts.append("")

    parts.append("## Worked examples")
    parts.append("")
    example_rows = []
    for ex in WORKED_EXAMPLES:
        score, band, esc = final_band(ex["S"], ex["L"], ex["G"])
        example_rows.append([
            ex["gap"], ex["standard"], ex["S"], ex["L"], ex["G"], score,
            band + (" (escalated)" if esc else ""),
        ])
    parts.append(_fmt_table(
        ["Gap", "Standard", "S", "L", "G", "Score", "Priority Band"], example_rows,
    ))
    parts.append("")
    for ex in WORKED_EXAMPLES:
        score, band, esc = final_band(ex["S"], ex["L"], ex["G"])
        marker = " Escalation applies." if esc else ""
        parts.append(f"- **{ex['gap']}** ({ex['S']} x {ex['L']} x {ex['G']} = {score}, "
                     f"{band}). {ex['note']}{marker}")
    parts.append("")

    parts.append("## Severity scale")
    parts.append("")
    parts.append(_fmt_table(
        ["S", "Obligation type"],
        [[s, SEVERITY_MEANING[s]] for s in sorted(SEVERITY_MEANING, reverse=True)],
    ))
    parts.append("")

    return "\n".join(parts)


def main():
    results_dir = "evaluation/results"
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, "risk_sensitivity.md")

    report = build_report()
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)

    rows = enumerate_space()
    counts = band_counts(rows)
    escalated = sum(1 for r in rows if r["escalated"])

    print(f"Enumerated {len(rows)} combinations")
    print(f"  Immediate:   {counts[IMMEDIATE]}")
    print(f"  Medium-term: {counts[MEDIUM]}")
    print(f"  Long-term:   {counts[LONG]}")
    print(f"  Escalated:   {escalated}")
    print(f"\nWritten to {path}")


if __name__ == "__main__":
    main()
