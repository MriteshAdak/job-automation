"""C15 RunSummary contracts.

Tracks pipeline run metrics with documented units, distinguishing source postings
from canonical jobs, and capturing errors and pending work.
"""

from __future__ import annotations

import uuid

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import RunStatus
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


class RunSummary(ContractModel):
    """C15 Pipeline Run Summary.

    Summarizes the execution of a discovery, assessment, and sync pipeline run.
    All counters have explicit documented units to prevent confusing source postings
    with canonical jobs.
    """

    run_id: uuid.UUID = Field(description="Unique pipeline execution UUID")
    start_time: UtcDatetime = Field(description="Pipeline run start timestamp (UTC)")
    end_time: UtcDatetime = Field(description="Pipeline run completion timestamp (UTC)")
    status: RunStatus = Field(description="Overall run status: success, partial, or failed")

    # Source posting metrics (Unit: raw source postings observed)
    source_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Map of source_key -> count of source postings observed",
    )
    source_postings_count: int = Field(
        ge=0,
        default=0,
        description="Total source postings observed across all sources in this run",
    )

    # Canonical job metrics (Unit: logical canonical jobs)
    canonical_jobs_new: int = Field(
        ge=0,
        default=0,
        description="Count of newly discovered canonical jobs registered",
    )
    canonical_jobs_updated: int = Field(
        ge=0,
        default=0,
        description="Count of existing canonical jobs that received new revisions",
    )
    canonical_jobs_duplicate: int = Field(
        ge=0,
        default=0,
        description="Count of postings identified as duplicates of existing canonical jobs",
    )

    # Disposition counts (Unit: canonical jobs evaluated in this run)
    eligible_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs classified as eligible",
    )
    review_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs flagged for candidate review",
    )
    rejected_count: int = Field(
        ge=0,
        default=0,
        description="Count of canonical jobs classified as rejected",
    )

    # Salesforce sync metrics (Unit: sync operations)
    sync_operations_succeeded: int = Field(
        ge=0,
        default=0,
        description="Count of sync operations successfully delivered to Salesforce",
    )
    sync_operations_failed: int = Field(
        ge=0,
        default=0,
        description="Count of sync operations that failed delivery",
    )

    # Diagnostic details
    errors: list[ClassifiedError] = Field(
        default_factory=list,
        description="Classified errors encountered during the run",
    )
    pending_work: list[str] = Field(
        default_factory=list,
        description="Descriptions of deferred or retry-waiting items",
    )

