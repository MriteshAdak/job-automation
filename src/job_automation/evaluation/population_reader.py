"""Read-only extraction of rejected job populations (EVAL-01-S07).

Reads production or exported assessment records to isolate candidate system rejects.
Enforces:
- Negative boundary: Zero Salesforce API calls or production table mutations.
- Negative boundary: Never reads or writes comparison records as production rejects.
- Excludes candidate-status Rejected, availability closures, and pending inferences.
- Computes deterministic frame hash for the eligible population.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.evaluation.fingerprints import compute_frame_hash


class RejectedJobCandidate(ContractModel):
    """An individual rejected job assessment considered for audit sampling."""

    canonical_job_id: uuid.UUID
    posting_revision: str
    title: str
    rejection_category: str  # hard_failure, exclusion, missing_policy, semantic_gap, low_score
    primary_reason: str
    hard_failure_reasons: list[str] = Field(default_factory=list)
    relevance_score: float | None = None
    final_disposition: str = "rejected"
    source_domain: str = "unknown"
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PopulationFilterResult(ContractModel):
    """Result of filtering the candidate population for audit sampling."""

    cohort_id: str
    eligible_candidates: list[RejectedJobCandidate]
    excluded_counts: dict[str, int]
    frame_hash: str


def read_rejected_population(
    records: Sequence[dict[str, Any]] | None = None,
    sqlite_db_path: Path | str | None = None,
    cohort_id: str = "cohort_2026_default",
) -> PopulationFilterResult:
    """Extract and filter rejected job assessments into a stable sampling frame.

    Excludes:
    - Comparison evaluation records (assessment_mode == 'comparison' or is_comparison == True).
    - Candidate application status 'Rejected' (human user job rejection, not system assessment rejection).
    - Availability closures (jobs closed before assessment finished).
    - Pending inference runs.
    """
    raw_records: list[dict[str, Any]] = []

    if sqlite_db_path is not None:
        db_p = Path(sqlite_db_path).resolve()
        if db_p.exists():
            conn = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                # Query assessments table if present
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='assessments'"
                )
                if cursor.fetchone():
                    cursor.execute(
                        "SELECT canonical_job_id, posting_revision, final_disposition, "
                        "relevance_score, summary_reason, assessment_method, "
                        "rule_outcomes_json, assessment_json FROM assessments "
                        "WHERE final_disposition = 'rejected'"
                    )
                    for r in cursor.fetchall():
                        raw_records.append(dict(r))
            finally:
                conn.close()

    if records:
        raw_records.extend(records)

    excluded_counts = {
        "comparison_records": 0,
        "candidate_status_rejected": 0,
        "availability_closure": 0,
        "pending_inference": 0,
    }

    eligible: list[RejectedJobCandidate] = []
    seen_canonical_jobs: set[str] = set()

    # Sort raw records by canonical_job_id and posting_revision for order invariance
    sorted_raw = sorted(
        raw_records,
        key=lambda r: (str(r.get("canonical_job_id", "")), str(r.get("posting_revision", ""))),
    )

    for r in sorted_raw:
        # Check exclusion 1: comparison records
        if r.get("assessment_mode") == "comparison" or r.get("is_comparison") is True:
            excluded_counts["comparison_records"] += 1
            continue

        # Check exclusion 2: candidate application status 'Rejected'
        if r.get("candidate_application_status") == "Rejected":
            excluded_counts["candidate_status_rejected"] += 1
            continue

        # Check exclusion 3: availability closure
        if r.get("closed_reason") == "availability" or r.get("is_closed_availability") is True:
            excluded_counts["availability_closure"] += 1
            continue

        # Check exclusion 4: pending inference
        if r.get("execution_status") == "pending" or r.get("status") == "pending":
            excluded_counts["pending_inference"] += 1
            continue

        # Check final disposition is rejected
        if r.get("final_disposition") != "rejected":
            continue

        c_job_id_str = str(r.get("canonical_job_id", uuid.uuid4()))
        # Deduplicate multiple scrapes/revisions for the same canonical opportunity
        if c_job_id_str in seen_canonical_jobs:
            continue
        seen_canonical_jobs.add(c_job_id_str)

        # Categorize primary rejection reason
        reason_cat = _classify_rejection_category(r)

        candidate = RejectedJobCandidate(
            canonical_job_id=uuid.UUID(c_job_id_str) if isinstance(r.get("canonical_job_id"), uuid.UUID) else uuid.UUID(c_job_id_str),
            posting_revision=str(r.get("posting_revision", "rev_1")),
            title=str(r.get("title", "Untitled Job")),
            rejection_category=reason_cat,
            primary_reason=str(r.get("summary_reason", "Rejection criterion triggered")),
            hard_failure_reasons=r.get("hard_failure_reasons", []),
            relevance_score=float(r["relevance_score"]) if r.get("relevance_score") is not None else None,
            source_domain=str(r.get("source_domain", "stepstone.de")),
        )
        eligible.append(candidate)

    # Compute deterministic frame hash
    eligible_hashes = [
        f"{c.canonical_job_id}:{c.posting_revision}:{c.rejection_category}"
        for c in eligible
    ]
    frame_hash = compute_frame_hash(eligible_hashes)

    return PopulationFilterResult(
        cohort_id=cohort_id,
        eligible_candidates=eligible,
        excluded_counts=excluded_counts,
        frame_hash=frame_hash,
    )


def _classify_rejection_category(record: dict[str, Any]) -> str:
    """Classify rejection into primary non-overlapping stratum."""
    summary = str(record.get("summary_reason", "")).lower()
    hard_fails = record.get("hard_failure_reasons", [])

    if hard_fails or "visa" in summary or "authorization" in summary or "location" in summary or "germany" in summary:
        return "hard_failure"
    if "exclusion" in summary or "blacklisted" in summary:
        return "exclusion"
    if "salary" in summary or "policy" in summary or "missing data" in summary:
        return "missing_policy"
    if "skill" in summary or "gap" in summary or "experience" in summary:
        return "semantic_gap"
    return "low_score"

