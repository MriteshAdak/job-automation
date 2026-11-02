"""Ports and protocol definitions for AUTO-02 automatic drafting."""

from __future__ import annotations

import uuid
from typing import Protocol

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
)


class CandidateReader(Protocol):
    """Protocol for reading candidates and their active production assessment envelopes."""

    def read_candidate_envelope(
        self,
        canonical_job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        org_id: str,
    ) -> tuple[AutomaticDraftCandidate | None, ClassifiedError | None]:
        """Read full candidate envelope for evaluation."""
        ...


class CandidateControlObserver(Protocol):
    """Protocol for observing fresh candidate-owned application status and opt-out."""

    def observe_candidate_control(
        self,
        canonical_job_id: uuid.UUID,
        candidate_id: uuid.UUID,
    ) -> tuple[str | None, bool, ClassifiedError | None]:
        """Return (application_state, opted_out, error)."""
        ...


class RequestAdmissionGateway(Protocol):
    """Protocol for admitting or dispatching automatic draft requests."""

    def publish_intent(
        self,
        intent: AutomaticDraftIntent,
    ) -> tuple[GenerationRequest | None, ClassifiedError | None]:
        """Publish or admit a reserved intent into an active GenerationRequest."""
        ...

