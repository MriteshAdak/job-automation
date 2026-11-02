"""C07 CanonicalJob and PostingRevision contracts.

Manages persistent canonical identities, company mappings, linked source postings,
revision lineage, and merge/split evidence.
"""

from __future__ import annotations

import uuid

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.primitives import (
    ContentHash,
    SourceKey,
    UtcDatetime,
)


class PostingRevision(ContractModel):
    """C07 Posting Revision.

    Represents a specific revision snapshot of a job posting observed at a given time.
    Different content hashes represent new revisions under the same canonical job.
    """

    revision_id: uuid.UUID = Field(description="UUID of this specific posting revision")
    canonical_job_id: uuid.UUID = Field(description="UUID of the parent canonical job")
    source_key: SourceKey = Field(description="Originating source key")
    content_hash: ContentHash = Field(description="SHA-256 hash of this revision's content")
    title: str = Field(min_length=1, description="Job title at this revision")
    first_seen_at: UtcDatetime = Field(description="When this revision was first observed")
    last_seen_at: UtcDatetime = Field(description="When this revision was most recently observed")
    source_urls: list[str] = Field(
        default_factory=list, description="All observed source URLs for this revision"
    )
    application_urls: list[str] = Field(
        default_factory=list, description="All observed application URLs for this revision"
    )
    availability: PostingAvailability = Field(
        default=PostingAvailability.ACTIVE,
        description="Availability status of this specific revision",
    )


class CanonicalJob(ContractModel):
    """C07 Canonical Job.

    Stable identity independent of mutable title/description/company name changes.
    Links one or more source postings and tracks full revision lineage.
    """

    canonical_job_id: uuid.UUID = Field(
        description="Stable canonical UUID assigned to this job opportunity"
    )
    canonical_company_id: uuid.UUID | None = Field(
        default=None,
        description="Stable UUID of the resolved company entity; null if unmapped",
    )
    company_name: str = Field(
        min_length=1,
        description="Canonical or best-known employer name",
    )
    linked_source_keys: list[SourceKey] = Field(
        default_factory=list,
        description="All source postings linked to this canonical job",
    )
    revisions: list[PostingRevision] = Field(
        default_factory=list,
        description="Ordered revision history for this job",
    )
    current_revision_id: uuid.UUID = Field(
        description="UUID of the active/latest posting revision",
    )
    first_seen_at: UtcDatetime = Field(
        description="Earliest observation timestamp across all linked sources",
    )
    last_seen_at: UtcDatetime = Field(
        description="Most recent observation timestamp across all linked sources",
    )
    availability: PostingAvailability = Field(
        default=PostingAvailability.ACTIVE,
        description="Overall canonical availability status",
    )
    merge_lineage: list[str] = Field(
        default_factory=list,
        description="Reversible audit trail of merge/split operations and evidence",
    )
    duplicate_proposal_reason: str | None = Field(
        default=None,
        description="Explanation if this job was flagged or resolved as a duplicate",
    )

