"""Data models for normalization and quarantine handoffs (INGEST-02).

Provides structured quarantine handoff envelopes preserving failed draft locators,
issue lists, and raw references without secret leakage.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey, UtcDatetime


class QuarantineHandoff(ContractModel):
    """Structured envelope for quarantined postings that failed normalization.

    Carries original raw reference, issue list, and input locators so failed
    records can be inspected, analyzed, or reprocessed without data loss.
    """

    quarantine_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique identifier for this quarantine event",
    )
    draft_reference: str = Field(
        description="Reference to the unnormalized raw posting",
    )
    raw_content_hash: str | None = Field(
        default=None,
        description="SHA-256 hash of raw input content if verified",
    )
    source_key: SourceKey | None = Field(
        default=None,
        description="Scoped source identity if available from draft",
    )
    mapping_version: str | None = Field(
        default=None,
        description="Source mapping version associated with the draft",
    )
    normalizer_version: str = Field(
        description="Version of the normalizer that produced this quarantine handoff",
    )
    observed_at: UtcDatetime | None = Field(
        default=None,
        description="Observation timestamp from the source draft",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Ordered list of validation issues that triggered quarantine",
    )
    input_ref: str | None = Field(
        default=None,
        description="Optional upstream parent file or batch reference",
    )
    record_index: int | None = Field(
        default=None,
        description="Optional zero-based record index within the parent batch",
    )
    quarantined_at: UtcDatetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the quarantine handoff was created (UTC)",
    )


class NormalizationResult(ContractModel):
    """Result of normalization with posting and quarantine envelope."""

    posting: NormalizedPosting | None = Field(
        default=None,
        description="Normalized posting if validation succeeded (or warnings only)",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="Validation issues produced during normalization",
    )
    quarantine: QuarantineHandoff | None = Field(
        default=None,
        description="Quarantine envelope if normalization failed",
    )

    @property
    def is_success(self) -> bool:
        """True if posting was successfully normalized without blocking errors."""
        return self.posting is not None and not any(
            iss.severity == "error" for iss in self.issues
        )

