"""C13 GenerationRequest contracts.

Represents a durable request to generate a tailored CV or cover letter.
Freezes input versions when claimed to prevent race conditions during generation.
"""

from __future__ import annotations

import uuid

from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


class FrozenInputVersions(ContractModel):
    """Snapshot of exact input versions frozen when a generation request is claimed."""

    posting_revision: str = Field(min_length=1, description="Job posting revision hash")
    profile_version: str = Field(min_length=1, description="Candidate profile version")
    policy_version: str = Field(min_length=1, description="Search policy version")
    template_version: str = Field(min_length=1, description="Document template version")


class GenerationRequest(ContractModel):
    """C13 Generation Request.

    Tracks a single generation job through pending, running, upload_pending,
    ready_for_review, or failed states. Retries preserve identity; deliberate
    regenerations receive a new request ID.
    """

    request_id: uuid.UUID = Field(description="Unique local generation request UUID")
    salesforce_request_id: str | None = Field(
        default=None,
        description="Salesforce Generation_Request__c record ID if created from Salesforce action",
    )
    client_request_key: str | None = Field(
        default=None,
        description="Idempotent client key for external or API-triggered requests",
    )
    canonical_job_id: uuid.UUID = Field(description="Target canonical job UUID")
    document_type: DocumentType = Field(description="Type of document: cv or cover_letter")
    target_language: str = Field(
        default="de",
        description="Requested document language (e.g. 'de', 'en')",
    )
    template_id: str = Field(
        min_length=1,
        description="Identifier of the layout template to render",
    )
    context_strategy: ContextStrategy = Field(
        default=ContextStrategy.JSON,
        description="Context strategy for generation: json or rag",
    )
    allow_unavailable_job: bool = Field(
        default=False,
        description="Explicit candidate override to draft for closed/unavailable job (default False)",
    )
    state: GenerationProcessing = Field(
        default=GenerationProcessing.PENDING,
        description="Current processing state of the generation request",
    )
    created_at: UtcDatetime = Field(description="Creation timestamp (UTC)")
    claimed_at: UtcDatetime | None = Field(
        default=None,
        description="When the worker claimed this request and froze inputs",
    )
    completed_at: UtcDatetime | None = Field(
        default=None,
        description="When generation and delivery reached terminal state",
    )
    frozen_input_versions: FrozenInputVersions | None = Field(
        default=None,
        description="Frozen input snapshots; required once request is claimed/running",
    )
    predecessor_request_id: uuid.UUID | None = Field(
        default=None,
        description="Linked predecessor request if this is a deliberate regeneration",
    )
    result_artifact_ref: str | None = Field(
        default=None,
        description="Reference to the locally saved C14 Artifact",
    )
    error: ClassifiedError | None = Field(
        default=None,
        description="Concise error classification if generation failed",
    )

    @model_validator(mode="after")
    def _validate_claimed_inputs(self) -> GenerationRequest:
        claimed_states = {
            GenerationProcessing.RUNNING,
            GenerationProcessing.UPLOAD_PENDING,
            GenerationProcessing.READY_FOR_REVIEW,
        }
        if self.state in claimed_states and self.frozen_input_versions is None:
            raise ValueError(
                f"Generation request in state '{self.state.value}' must have frozen_input_versions"
            )
        return self

