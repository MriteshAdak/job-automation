"""Read-only inspection models and summaries for availability (IDENTITY-02-S07).

Provides safe diagnostics:
- Redacts raw text, secrets, or sensitive URL tokens.
- Reports clear reason codes, policy version, and pending conditions.
"""

from __future__ import annotations

import uuid

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import UtcDatetime
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    SourcePostingAvailability,
)


class CanonicalAvailabilitySummary(ContractModel):
    """Inspectable diagnostic view of a canonical job's availability posture."""

    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    company_name: str = Field(description="Company employer name")
    canonical_availability: PostingAvailability = Field(description="Aggregated canonical availability")
    first_seen_at: UtcDatetime = Field(description="Earliest observation timestamp")
    last_seen_at: UtcDatetime = Field(description="Most recent observation timestamp")
    explanation: str = Field(description="Human-readable aggregation reason")
    linked_sources_count: int = Field(ge=0, description="Total number of linked source postings")
    active_sources_count: int = Field(ge=0, description="Number of currently active source postings")
    source_states: list[SourcePostingAvailability] = Field(
        default_factory=list,
        description="Detailed per-source availability states",
    )
    recent_decisions: list[AvailabilityDecision] = Field(
        default_factory=list,
        description="Recent audit decisions affecting this job",
    )

