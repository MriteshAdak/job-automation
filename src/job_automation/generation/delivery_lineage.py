"""Lineage validation and approval isolation for deliberate regenerations (GEN-06-S06)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import GenerationRequest
from job_automation.storage.repositories.artifacts import ArtifactRepository
from job_automation.storage.repositories.generation_requests import GenerationRequestRepository

logger = logging.getLogger(__name__)


def validate_regeneration_lineage(
    request: GenerationRequest,
    requests_repo: GenerationRequestRepository,
) -> tuple[bool, ClassifiedError | None]:
    """Verify predecessor request linkage for a deliberate regeneration."""
    if not request.predecessor_request_id:
        return True, None

    if request.predecessor_request_id == request.request_id:
        return False, ClassifiedError.validation(
            f"Cyclic regeneration: request {request.request_id} references itself as predecessor"
        )

    predecessor = requests_repo.get_request(request.predecessor_request_id)
    if predecessor is None:
        return False, ClassifiedError.validation(
            f"Predecessor generation request {request.predecessor_request_id} not found in storage"
        )

    if predecessor.canonical_job_id != request.canonical_job_id:
        return False, ClassifiedError.validation(
            f"Job mismatch in regeneration: current job {request.canonical_job_id} != predecessor job {predecessor.canonical_job_id}"
        )

    return True, None


def ensure_draft_approval_status(artifacts: list[Artifact]) -> None:
    """Ensure that freshly delivered artifacts maintain strict DRAFT approval status."""
    for art in artifacts:
        if art.approval_status != DocumentApproval.DRAFT:
            raise ValueError(
                f"Artifact {art.artifact_id} has invalid approval status '{art.approval_status}'. "
                "Delivered artifacts must strictly remain 'draft' until explicit human approval."
            )

