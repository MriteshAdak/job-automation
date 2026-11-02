"""Protocol definitions for CONTEXT-04 context selector and retrieval components."""

from __future__ import annotations

import uuid
from typing import Protocol, Sequence, runtime_checkable

from job_automation.context.records import PreparedProfileContext
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
    FusedCandidate,
    RequirementQuerySet,
    RetrievalHit,
    RetrievalTrace,
)
from job_automation.context.index_ports import IndexHandlePort
from job_automation.contracts.errors import ClassifiedError


@runtime_checkable
class ContextSelectorV2Port(Protocol):
    """Public V2 boundary protocol for shared context selection (JSON or RAG)."""

    def select_context(
        self,
        request: ContextSelectionRequest,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Select context according to request strategy and return complete result or ClassifiedError."""
        ...


@runtime_checkable
class QueryBuilderPort(Protocol):
    """Boundary for deterministic requirement query set construction."""

    def build_queries(
        self,
        requirements: Sequence[str],
        fallback_job_text: str | None = None,
    ) -> RequirementQuerySet:
        """Construct normalized requirement queries with deterministic fingerprint."""
        ...


@runtime_checkable
class RAGContextBuilderPort(Protocol):
    """Boundary for RAG evidence retrieval, fusion, and budget packing."""

    def build_rag_context(
        self,
        request: ContextSelectionRequest,
        prepared: PreparedProfileContext,
        index_handle: IndexHandlePort,
    ) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
        """Retrieve, fuse, pack, and measure RAG context bundle."""
        ...
