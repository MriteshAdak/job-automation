"""Port and protocol definitions for CONTEXT-02 evidence chunking."""

from __future__ import annotations

import uuid
from typing import Protocol

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.evidence_chunks import (
    ChunkBuildRequest,
    ChunkChangeSet,
    ChunkSet,
    ChunkingSettings,
    EvidenceChunk,
)


class EvidenceChunkerPort(Protocol):
    """Protocol for the public offline chunking service."""

    def build(self, request: ChunkBuildRequest) -> tuple[ChunkSet | None, ClassifiedError | None]:
        """Construct deterministic ChunkSet or return ClassifiedError."""
        ...

    def diff(
        self, base_manifest: ChunkSet, target_manifest: ChunkSet
    ) -> tuple[ChunkChangeSet | None, ClassifiedError | None]:
        """Compare base and target manifests to produce invalidation changes."""
        ...

    def validate_binding(
        self,
        chunk_set: ChunkSet,
        expected_candidate_id: uuid.UUID,
        expected_profile_version: str,
        expected_purpose: str,
        expected_settings_fingerprint: str | None = None,
    ) -> tuple[bool, ClassifiedError | None]:
        """Verify that a manifest satisfies exact caller binding requirements."""
        ...


class ChunkRendererPort(Protocol):
    """Protocol for rendering retrieval text from prepared candidate evidence."""

    def render(self, chunk: EvidenceChunk, settings: ChunkingSettings) -> str:
        """Render deterministic retrieval text."""
        ...

