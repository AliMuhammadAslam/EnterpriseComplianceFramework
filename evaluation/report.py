from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class Gap(BaseModel):
    area: str
    description: str
    standard_reference: str
    risk_level: str  # "Critical", "High", "Medium", "Low"
    current_state: str
    required_state: str


class ComplianceArea(BaseModel):
    area: str
    description: str
    standard_reference: str
    evidence: str = ""


class Recommendation(BaseModel):
    priority: int
    title: str
    description: str
    standard_reference: str
    expected_effort: str = ""
    risk_addressed: str = ""


class RiskItem(BaseModel):
    risk: str
    likelihood: str  # "High", "Medium", "Low"
    impact: str  # "High", "Medium", "Low"
    overall_risk_level: str  # "Critical", "High", "Medium", "Low"
    related_gaps: List[str] = []
    mitigation: str = ""


class EvaluationReport(BaseModel):
    title: str
    generated_at: str = ""
    company_context: str = ""
    standards_evaluated: List[str] = []
    industry: str = ""
    country: str = ""

    # Report sections
    executive_summary: str = ""
    compliant_areas: List[ComplianceArea] = []
    gaps: List[Gap] = []
    risk_assessment: List[RiskItem] = []
    recommendations: List[Recommendation] = []

    overall_compliance_score: str = ""  # e.g. "Partial", "Strong", etc.
    overall_risk_level: str = ""


def format_report(report: EvaluationReport) -> str:
    """Format an EvaluationReport into a readable markdown string."""
    lines = []

    lines.append(f"# {report.title}")
    lines.append(f"\n**Generated**: {report.generated_at}")
    if report.industry:
        lines.append(f"**Industry**: {report.industry}")
    if report.country:
        lines.append(f"**Country/Jurisdiction**: {report.country}")
    lines.append(
        f"**Standards Evaluated**: {', '.join(report.standards_evaluated)}"
    )
    if report.overall_compliance_score:
        lines.append(
            f"**Overall Compliance Score**: {report.overall_compliance_score}"
        )
    if report.overall_risk_level:
        lines.append(
            f"**Overall Risk Level**: {report.overall_risk_level}"
        )

    # Executive Summary
    lines.append("\n---\n## Executive Summary")
    lines.append(report.executive_summary)

    # Compliant Areas
    if report.compliant_areas:
        lines.append("\n---\n## Compliant Areas")
        for i, area in enumerate(report.compliant_areas, 1):
            lines.append(f"\n### {i}. {area.area}")
            lines.append(f"- **Description**: {area.description}")
            lines.append(f"- **Standard Reference**: {area.standard_reference}")
            if area.evidence:
                lines.append(f"- **Evidence**: {area.evidence}")

    # Gap Analysis
    if report.gaps:
        lines.append("\n---\n## Gap Analysis")
        for i, gap in enumerate(report.gaps, 1):
            risk_emoji = {
                "Critical": "🔴",
                "High": "🟠",
                "Medium": "🟡",
                "Low": "🟢",
            }.get(gap.risk_level, "⚪")
            lines.append(f"\n### {i}. {gap.area} {risk_emoji}")
            lines.append(f"- **Risk Level**: {gap.risk_level}")
            lines.append(f"- **Description**: {gap.description}")
            lines.append(f"- **Standard Reference**: {gap.standard_reference}")
            lines.append(f"- **Current State**: {gap.current_state}")
            lines.append(f"- **Required State**: {gap.required_state}")

    # Risk Assessment
    if report.risk_assessment:
        lines.append("\n---\n## Risk Assessment")
        lines.append(
            "\n| Risk | Likelihood | Impact | Level | Mitigation |"
        )
        lines.append(
            "|------|-----------|--------|-------|------------|"
        )
        for risk in report.risk_assessment:
            lines.append(
                f"| {risk.risk} | {risk.likelihood} | {risk.impact} "
                f"| {risk.overall_risk_level} | {risk.mitigation} |"
            )

    # Recommendations
    if report.recommendations:
        lines.append("\n---\n## Recommendations")
        for rec in report.recommendations:
            lines.append(f"\n### Priority {rec.priority}: {rec.title}")
            lines.append(f"- **Description**: {rec.description}")
            lines.append(
                f"- **Standard Reference**: {rec.standard_reference}"
            )
            if rec.expected_effort:
                lines.append(f"- **Expected Effort**: {rec.expected_effort}")
            if rec.risk_addressed:
                lines.append(f"- **Risk Addressed**: {rec.risk_addressed}")

    return "\n".join(lines)
