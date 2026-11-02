"""Protocols and port definitions for MATCH-01 assessment boundary."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import ProfileSnapshot


@runtime_checkable
class PostingReader(Protocol):
    """Protocol for reading normalized postings by source key or revision."""

    def get_normalized_posting(self, source_key: SourceKey) -> NormalizedPosting | None:
        """Fetch normalized posting for a source key."""
        ...


@runtime_checkable
class ProfileReader(Protocol):
    """Protocol for fetching candidate profiles by ID and version."""

    def get_approved_snapshot(
        self,
        candidate_id: uuid.UUID,
        version: str | None = None,
    ) -> ProfileSnapshot | None:
        """Fetch an approved profile snapshot."""
        ...


@runtime_checkable
class AssessmentRepositoryPort(Protocol):
    """Protocol for persisting C11 Assessment records."""

    def save_assessment(self, assessment: Assessment) -> None:
        """Persist an assessment record."""
        ...

