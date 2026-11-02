"""Deterministic text rendering for CONTEXT-02 evidence chunks.

Guarantees:
- Granularity: One complete primary fact per chunk.
- Separately attributed permitted ancestor context anchors.
- Approved title, organization, claims, skills, and metrics preserved verbatim.
- Dates retain exact value and precision; null end dates never become 'present'.
- No duration calculation, no skill inheritance, no LLM paraphrasing or synthesis.
- Preserves qualifiers, negation, list order, duplicates, and Unicode characters.
"""

from __future__ import annotations

from typing import Sequence

from job_automation.contracts.evidence_chunks import AncestorContext
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact


def _format_precision_dates(
    start_date: PrecisionDate | None, end_date: PrecisionDate | None
) -> str | None:
    """Format precision dates preserving exact value without duration or fabricated present."""
    if start_date is not None and end_date is not None:
        return f"Dates: {start_date.value} to {end_date.value}"
    if start_date is not None:
        return f"Start Date: {start_date.value}"
    if end_date is not None:
        return f"End Date: {end_date.value}"
    return None


class DefaultChunkRenderer:
    """Renders deterministic retrieval text for an evidence chunk."""

    def render(
        self,
        primary_fact: CandidateFact,
        ancestors: Sequence[AncestorContext],
    ) -> str:
        """Render complete structured evidence text."""
        sections: list[str] = []

        # 1. Permitted ancestor context (if any)
        if ancestors:
            sections.append("[Parent Context]")
            for anc in ancestors:
                lines: list[str] = [
                    f"Kind: {anc.kind.value}",
                    f"Title: {anc.title}",
                ]
                if anc.organization is not None:
                    lines.append(f"Organization: {anc.organization}")
                date_str = _format_precision_dates(anc.start_date, anc.end_date)
                if date_str:
                    lines.append(date_str)
                sections.append("\n".join(lines))

        # 2. Primary evidence
        primary_lines: list[str] = [
            "[Evidence]",
            f"Kind: {primary_fact.kind.value}",
            f"Title: {primary_fact.title}",
        ]
        if primary_fact.organization is not None:
            primary_lines.append(f"Organization: {primary_fact.organization}")

        date_str = _format_precision_dates(primary_fact.start_date, primary_fact.end_date)
        if date_str:
            primary_lines.append(date_str)

        if primary_fact.claims:
            primary_lines.append("Claims:")
            for claim in primary_fact.claims:
                primary_lines.append(f"- {claim}")

        if primary_fact.skills:
            primary_lines.append(f"Skills: {', '.join(primary_fact.skills)}")

        if primary_fact.metrics:
            primary_lines.append("Metrics:")
            for metric in primary_fact.metrics:
                primary_lines.append(f"- {metric}")

        sections.append("\n".join(primary_lines))

        return "\n\n".join(sections)

