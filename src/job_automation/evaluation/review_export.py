"""Review packet export utilities (EVAL-01-S06).

Exports blinded evaluation review packets and correction templates to JSON.
Guarantees that sensitive production credentials or live Salesforce links
are never included in exported review files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from job_automation.evaluation.records import EvaluationCase, PairResult
from job_automation.evaluation.review import ReviewPacket, generate_blinded_review_packet


def export_review_packets(
    cases: Sequence[EvaluationCase],
    pair_results: Sequence[PairResult],
    output_path: Path,
    seed: int = 42,
) -> Path:
    """Export blinded review packets for completed pairs to a JSON file."""
    case_map = {c.case_id: c for c in cases}
    packets: list[ReviewPacket] = []

    for pair in pair_results:
        if not pair.pair_completed:
            continue
        case = case_map.get(pair.case_id)
        if not case:
            continue
        pkt = generate_blinded_review_packet(case, pair, seed=seed)
        packets.append(pkt)

    output_data = {
        "version": "1.0",
        "total_packets": len(packets),
        "packets": [p.model_dump(mode="json") for p in packets],
        "correction_template_example": {
            "case_id": "case_example",
            "reviewer_id": "human_reviewer_01",
            "target_type": "model_finding",
            "old_value": {"status": "match"},
            "new_value": {"status": "gap"},
            "reason": "Cited evidence did not demonstrate required seniority",
            "supporting_evidence": [
                {
                    "source_kind": "candidate",
                    "profile_version": "v1",
                    "fact_id": "00000000-0000-0000-0000-000000000001",
                }
            ],
            "active_review_seconds": 45.0,
            "adjudication_status": "adjudicated",
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    return output_path

