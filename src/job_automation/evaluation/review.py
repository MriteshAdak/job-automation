"""Blinded reviewer packet generation and review data structures (EVAL-01-S06).

Provides:
- Blinding of context strategy (Strategy A vs Strategy B) with randomized order.
- Extraction of observable model findings and citations for human review.
- Active reviewer effort time recording.
- Strict isolation: candidate profile truth and search policy cannot be altered.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Sequence

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import ContextStrategy
from job_automation.evaluation.records import EvaluationCase, PairResult, ReviewCorrection


class BlindedArmView(ContractModel):
    """Blinded presentation of an arm's assessment output."""

    arm_label: Literal["Arm A", "Arm B"]
    relevance_score: float | None = None
    final_disposition: str
    summary_reason: str
    rule_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    unsupported_claims_flagged: list[str] = Field(default_factory=list)


class ReviewPacket(ContractModel):
    """Blinded review unit presented to human reviewer."""

    packet_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    case_id: str
    pair_id: uuid.UUID
    experiment_id: uuid.UUID
    posting_title: str
    posting_description: str
    arm_a: BlindedArmView
    arm_b: BlindedArmView
    blinding_key: str = Field(
        description="Encrypted or hashed key mapping Arm A and Arm B back to JSON / RAG",
    )
    gold_requirements_summary: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def generate_blinded_review_packet(
    case: EvaluationCase,
    pair: PairResult,
    seed: int = 42,
) -> ReviewPacket:
    """Generate a blinded review packet for a completed pair, randomizing Arm A / B."""
    rng = random.Random(f"{pair.pair_id}_{seed}")
    # Randomly decide whether Arm A is JSON or RAG
    json_is_a = rng.choice([True, False])

    def _make_arm_view(label: Literal["Arm A", "Arm B"], arm) -> BlindedArmView:
        asmt = arm.final_assessment
        if asmt is None:
            return BlindedArmView(
                arm_label=label,
                final_disposition="FAILED",
                summary_reason="Arm execution failed or overflowed",
            )
        findings_data = []
        for f in asmt.requirement_findings:
            findings_data.append({
                "requirement_id": f.requirement_id,
                "requirement_text": f.requirement_text,
                "status": f.status.value,
                "reason": f.reason,
                "citations": [str(c.fact_id) for c in f.candidate_evidence],
            })
        rule_data = [
            {"criterion_name": r.criterion_name, "result": r.result.value, "reason": r.reason}
            for r in asmt.rule_outcomes
        ]
        return BlindedArmView(
            arm_label=label,
            relevance_score=asmt.relevance_score,
            final_disposition=asmt.final_disposition.value,
            summary_reason=asmt.summary_reason,
            rule_outcomes=rule_data,
            findings=findings_data,
        )

    if json_is_a:
        arm_a = _make_arm_view("Arm A", pair.json_arm)
        arm_b = _make_arm_view("Arm B", pair.rag_arm)
        blinding_key = "A=JSON;B=RAG"
    else:
        arm_a = _make_arm_view("Arm A", pair.rag_arm)
        arm_b = _make_arm_view("Arm B", pair.json_arm)
        blinding_key = "A=RAG;B=JSON"

    gold_summary = [
        {
            "requirement_id": r.requirement_id,
            "text": r.text,
            "gold_status": r.gold_status.value,
            "sufficient_evidence_sets": r.sufficient_evidence_sets,
        }
        for r in case.gold_label.requirements
    ]

    return ReviewPacket(
        case_id=case.case_id,
        pair_id=pair.pair_id,
        experiment_id=pair.experiment_id,
        posting_title=case.posting.title,
        posting_description=case.posting.description_clean,
        arm_a=arm_a,
        arm_b=arm_b,
        blinding_key=blinding_key,
        gold_requirements_summary=gold_summary,
    )

