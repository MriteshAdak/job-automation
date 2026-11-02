"""Service-independent interface boundaries (Protocols) for retrieval indexing."""

from __future__ import annotations

import uuid
from typing import Any, Protocol, Sequence, runtime_checkable

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.evidence_chunks import EvidenceChunk
from job_automation.contracts.retrieval_index import (
    IndexBuildRequest,
    IndexBuildResult,
    IndexManifest,
    IndexReadRequest,
    TermPosting,
)


@runtime_checkable
class IndexHandlePort(Protocol):
    """Protocol for an open, read-only index generation handle."""

    @property
    def row_count(self) -> int:
        """Total number of indexed evidence chunk rows."""
        ...

    @property
    def dimension(self) -> int:
        """Vector embedding dimension."""
        ...

    @property
    def manifest(self) -> IndexManifest:
        """Complete immutable generation manifest."""
        ...

    def get_vector(self, row_ordinal: int) -> list[float]:
        """Retrieve single embedding vector by row ordinal."""
        ...

    def get_vectors(self, row_ordinals: Sequence[int] | None = None) -> list[list[float]]:
        """Retrieve ordered embedding vectors for row ordinals (or all if None)."""
        ...

    def lookup_term(self, term: str) -> list[TermPosting]:
        """Find postings for a single normalized search term."""
        ...

    def lookup_terms(self, terms: Sequence[str]) -> dict[str, list[TermPosting]]:
        """Find postings for multiple search terms."""
        ...

    def get_chunk(self, row_ordinal: int) -> EvidenceChunk:
        """Retrieve source EvidenceChunk by row ordinal."""
        ...

    def get_chunk_by_id(self, chunk_id: uuid.UUID) -> EvidenceChunk | None:
        """Retrieve source EvidenceChunk by its stable chunk_id."""
        ...

    def validate_query_embedding_space(self, query_embedding_space_fingerprint: str) -> None:
        """Validate query vector space compatibility before similarity calculation."""
        ...

    def close(self) -> None:
        """Release open file handles and locks."""
        ...

    def __enter__(self) -> IndexHandlePort:
        ...

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        ...


@runtime_checkable
class IndexBuilderPort(Protocol):
    """Protocol for local vector and keyword index construction."""

    def build(
        self,
        request: IndexBuildRequest,
    ) -> tuple[IndexBuildResult | None, ClassifiedError | None]:
        """Construct local vector and keyword index for target chunk set.

        Invariant: Exactly one of (result, error) is non-null.
        """
        ...


@runtime_checkable
class IndexStorePort(Protocol):
    """Protocol for reading and managing persisted index generations."""

    def open(
        self,
        request: IndexReadRequest,
    ) -> tuple[IndexHandlePort | None, ClassifiedError | None]:
        """Open a verified, read-only handle to the active (or frozen) index.

        Invariant: Exactly one of (handle, error) is non-null.
        """
        ...

