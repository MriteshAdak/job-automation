"""Protocols and interfaces for GEN-02 standalone input service and context access."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.input_records import (
    FrozenContextReceipt,
    FrozenSeal,
    PreflightReceipt,
)
from job_automation.generation.records import FreezeManifest


@runtime_checkable
class StandaloneGenerationInputService(Protocol):
    """Worker-independent input service interface for preflight, sealing, and context access."""

    def prepare_freeze(
        self,
        request: GenerationRequest,
        freeze_op_id: str,
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        """Recheck availability, validate options, and atomically seal immutable inputs."""
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
        """Build or retrieve context bundle (JSON or RAG) strictly from frozen snapshots."""
        ...

    def inspect_preflight(
        self,
        request_id: uuid.UUID,
    ) -> PreflightReceipt | None:
        """Inspect durable preflight receipt and audit decision without worker."""
        ...

    def reopen_context(
        self,
        receipt_id: uuid.UUID,
    ) -> tuple[FrozenContextReceipt | None, ClassifiedError | None]:
        """Retrieve complete context selection result (bundle, rendered prompt, trace) for GEN-03."""
        ...

    def get_seal(
        self,
        request_id: uuid.UUID,
    ) -> tuple[FrozenSeal | None, ClassifiedError | None]:
        """Retrieve complete frozen seal including all component snapshots."""
        ...

    def get_context_receipt_by_request(
        self,
        request_id: uuid.UUID,
    ) -> tuple[FrozenContextReceipt | None, ClassifiedError | None]:
        """Retrieve durable context receipt by generation request UUID."""
        ...

