"""GEN-01 port protocols defining component boundaries (DG1–DG5)."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.interfaces import Generator, RendererDelivery, SalesforceGatewayV2
from job_automation.generation.records import (
    ArtifactDeliveryRecord,
    FreezeManifest,
    GenerationRequestObservation,
    ProjectionIntent,
    ValidationReport,
)


@runtime_checkable
class GenerationRequestSource(Protocol):
    """Adapter for discovering remote generation requests (SF-05/SFCLIENT-01)."""

    def poll_requests(
        self,
        lane: str,
        continuation_token: str | None = None,
        limit: int = 20,
    ) -> tuple[list[GenerationRequestObservation], str | None, ClassifiedError | None]:
        """Fetch a page of remote generation request observations."""
        ...

    def get_request(
        self,
        salesforce_request_id: str,
    ) -> tuple[GenerationRequestObservation | None, ClassifiedError | None]:
        """Fetch a single remote generation request by Salesforce record ID."""
        ...


@runtime_checkable
class GenerationInputService(Protocol):
    """GEN-02 port for input freezing, validation, and context construction."""

    def prepare_freeze(
        self,
        request: GenerationRequest,
        freeze_op_id: str,
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        """Validate options and snapshot inputs into an immutable freeze manifest."""
        ...

    def reopen_freeze(
        self,
        manifest_id: str,
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        """Reopen and verify an existing sealed freeze manifest."""
        ...

    def build_context(
        self,
        manifest: FreezeManifest,
        context_op_id: str,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Build context bundle (JSON or RAG) strictly from frozen snapshots."""
        ...


@runtime_checkable
class DraftValidator(Protocol):
    """GEN-04 port for factual and semantic document validation."""

    def validate_draft(
        self,
        draft: DraftDocument | DraftDocumentV2,
        manifest: FreezeManifest,
    ) -> tuple[ValidationReport | None, ClassifiedError | None]:
        """Validate draft content and claims against frozen inputs."""
        ...


@runtime_checkable
class DocumentRenderer(Protocol):
    """GEN-05 port for rendering structured drafts into physical files."""

    def render_document(
        self,
        draft: DraftDocument | DraftDocumentV2,
        output_format: str,
        destination_path: str,
        op_id: str,
    ) -> tuple[Artifact | None, ClassifiedError | None]:
        """Render a draft into the requested format (DOCX or PDF)."""
        ...


@runtime_checkable
class ArtifactDeliverer(Protocol):
    """GEN-06 port for delivering artifacts and reconciling upload state."""

    def deliver_artifact(
        self,
        artifact: Artifact,
        gateway: SalesforceGatewayV2,
        op_id: str,
    ) -> tuple[ArtifactDeliveryRecord | None, ClassifiedError | None]:
        """Deliver artifact to Salesforce Files with idempotent receipts."""
        ...

    def reconcile_delivery(
        self,
        request_id: uuid.UUID,
        output_format: str,
    ) -> tuple[ArtifactDeliveryRecord | None, ClassifiedError | None]:
        """Reconcile ambiguous upload outcomes for an artifact slot."""
        ...


@runtime_checkable
class RequestStateProjector(Protocol):
    """Port for projecting durable local request states to Salesforce."""

    def project_intent(
        self,
        intent: ProjectionIntent,
    ) -> tuple[bool, ClassifiedError | None]:
        """Dispatch a state projection intent to the remote gateway."""
        ...

    def reconcile_intent(
        self,
        intent: ProjectionIntent,
    ) -> tuple[bool, ClassifiedError | None]:
        """Reconcile an uncertain or unacknowledged projection intent."""
        ...

