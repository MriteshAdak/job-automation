"""Guarded read-only index handle and store access conforming to IndexStorePort."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Sequence

from job_automation.context.index_errors import (
    IndexBindingError,
    IndexIncompatibleError,
    IndexStaleError,
    IndexValidationError,
    map_index_exception_to_classified_error,
)
from job_automation.context.index_files import (
    CHUNKS_FILENAME,
    KEYWORDS_FILENAME,
    MANIFEST_FILENAME,
    VECTORS_FILENAME,
    verify_generation_files,
)
from job_automation.context.index_ports import IndexHandlePort, IndexStorePort
from job_automation.context.index_serialization import (
    read_chunks_file,
    read_manifest_file,
)
from job_automation.context.keyword_index import KeywordIndexReader
from job_automation.context.vector_matrix import VectorMatrixReader
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.evidence_chunks import EvidenceChunk
from job_automation.contracts.retrieval_index import (
    IndexManifest,
    IndexReadRequest,
    TermPosting,
)
from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexHandle(IndexHandlePort):
    """Verified, read-only handle to an active or pinned index generation."""

    def __init__(
        self,
        manifest: IndexManifest,
        generation_dir: Path,
        activation_token: str | None = None,
    ) -> None:
        self._manifest = manifest
        self.generation_dir = generation_dir
        self.activation_token = activation_token

        # Initialize underlying readers
        self._matrix_reader = VectorMatrixReader(
            path=generation_dir / VECTORS_FILENAME,
            row_count=manifest.row_count,
            dimension=manifest.dimension,
        )
        self._keyword_reader = KeywordIndexReader(
            db_path=generation_dir / KEYWORDS_FILENAME
        )

        # Load canonical exported chunks
        self._chunks = read_chunks_file(generation_dir / CHUNKS_FILENAME)
        self._chunks_by_id = {c.chunk_id: c for c in self._chunks}
        self._is_closed = False

    @property
    def row_count(self) -> int:
        return self._manifest.row_count

    @property
    def dimension(self) -> int:
        return self._manifest.dimension

    @property
    def manifest(self) -> IndexManifest:
        return self._manifest

    def get_vector(self, row_ordinal: int) -> list[float]:
        self._ensure_open()
        return self._matrix_reader.read_vector(row_ordinal)

    def get_vectors(self, row_ordinals: Sequence[int] | None = None) -> list[list[float]]:
        self._ensure_open()
        return self._matrix_reader.read_vectors(row_ordinals)

    def lookup_term(self, term: str) -> list[TermPosting]:
        self._ensure_open()
        return self._keyword_reader.lookup_term(term)

    def lookup_terms(self, terms: Sequence[str]) -> dict[str, list[TermPosting]]:
        self._ensure_open()
        return self._keyword_reader.lookup_terms(terms)

    def get_chunk(self, row_ordinal: int) -> EvidenceChunk:
        self._ensure_open()
        if not (0 <= row_ordinal < len(self._chunks)):
            raise IndexError(f"Row ordinal {row_ordinal} out of range [0, {len(self._chunks)})")
        return self._chunks[row_ordinal]

    def get_chunk_by_id(self, chunk_id: uuid.UUID) -> EvidenceChunk | None:
        self._ensure_open()
        return self._chunks_by_id.get(chunk_id)

    def validate_query_embedding_space(
        self,
        query_embedding_space_fingerprint: str,
    ) -> None:
        """Verify that query vector space matches the index before comparison."""
        self._ensure_open()
        if query_embedding_space_fingerprint != self._manifest.embedding_space_fingerprint:
            raise IndexIncompatibleError(
                f"Query embedding space '{query_embedding_space_fingerprint}' is incompatible with index space '{self._manifest.embedding_space_fingerprint}'",
                field_path="query_embedding_space_fingerprint",
                details={
                    "query_space": query_embedding_space_fingerprint,
                    "index_space": self._manifest.embedding_space_fingerprint,
                },
            )

    def close(self) -> None:
        if not self._is_closed:
            self._keyword_reader.close()
            self._is_closed = True

    def _ensure_open(self) -> None:
        if self._is_closed:
            raise ValueError("Cannot read from a closed IndexHandle")

    def __enter__(self) -> IndexHandle:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()


class IndexStore(IndexStorePort):
    """Guarded entry point for opening verified read-only index handles."""

    def __init__(
        self,
        indexes_dir: Path | str,
        repository: ContextIndexRepository,
    ) -> None:
        self.indexes_dir = Path(indexes_dir)
        self.repository = repository

    def open(
        self,
        request: IndexReadRequest,
    ) -> tuple[IndexHandlePort | None, ClassifiedError | None]:
        """Open a verified read-only handle conforming to expected bindings."""
        try:
            if request.authorization_mode == "current_use":
                active = self.repository.get_active_generation(
                    request.candidate_id, request.purpose
                )
                if active is None:
                    raise IndexBindingError(
                        f"No active index generation found for candidate '{request.candidate_id}' and purpose '{request.purpose}'",
                        field_path="candidate_id",
                    )

                if active["status"] != "active":
                    raise IndexStaleError(
                        f"Active generation pointer has status '{active['status']}', expected 'active'",
                        field_path="status",
                    )

                # Check expected profile version
                if request.expected_profile_version is not None:
                    if active["profile_version"] != request.expected_profile_version:
                        raise IndexStaleError(
                            f"Active index profile version '{active['profile_version']}' does not match expected '{request.expected_profile_version}'",
                            field_path="profile_version",
                            details={
                                "active_version": active["profile_version"],
                                "expected_version": request.expected_profile_version,
                            },
                        )

                # Check expected fingerprints
                if request.expected_snapshot_fingerprint is not None:
                    if active["snapshot_fingerprint"] != request.expected_snapshot_fingerprint:
                        raise IndexStaleError(
                            "Snapshot fingerprint mismatch against active index",
                            field_path="snapshot_fingerprint",
                        )

                if request.expected_chunk_manifest_hash is not None:
                    if active["chunk_manifest_hash"] != request.expected_chunk_manifest_hash:
                        raise IndexStaleError(
                            "Chunk manifest fingerprint mismatch against active index",
                            field_path="chunk_manifest_hash",
                        )

                if request.expected_embedding_space_fingerprint is not None:
                    if active["embedding_space_fingerprint"] != request.expected_embedding_space_fingerprint:
                        raise IndexIncompatibleError(
                            "Embedding space fingerprint mismatch against active index",
                            field_path="embedding_space_fingerprint",
                        )

                if request.expected_settings_fingerprint is not None:
                    if active["settings_fingerprint"] != request.expected_settings_fingerprint:
                        raise IndexIncompatibleError(
                            "Index settings fingerprint mismatch against active index",
                            field_path="settings_fingerprint",
                        )

                gen_dir = Path(active["generation_dir"])
                manifest = IndexManifest.model_validate_json(active["manifest_json"])
                verify_generation_files(gen_dir, manifest)

                handle = IndexHandle(
                    manifest=manifest,
                    generation_dir=gen_dir,
                    activation_token=active["activation_token"],
                )
                return handle, None

            elif request.authorization_mode == "frozen_use":
                if request.frozen_generation_id is None:
                    raise IndexBindingError(
                        "frozen_generation_id is required when authorization_mode is 'frozen_use'",
                        field_path="frozen_generation_id",
                    )

                frozen_id = request.frozen_generation_id
                if not self.repository.is_generation_pinned(frozen_id):
                    raise IndexBindingError(
                        f"Frozen generation '{frozen_id}' is not pinned for authorized use",
                        field_path="frozen_generation_id",
                    )

                gen = self.repository.get_generation(frozen_id)
                if gen is None:
                    raise IndexBindingError(
                        f"Frozen generation '{frozen_id}' not found",
                        field_path="frozen_generation_id",
                    )

                gen_dir = Path(gen["generation_dir"])
                manifest = IndexManifest.model_validate_json(gen["manifest_json"])
                verify_generation_files(gen_dir, manifest)

                handle = IndexHandle(
                    manifest=manifest,
                    generation_dir=gen_dir,
                    activation_token=None,
                )
                return handle, None

            else:
                raise IndexValidationError(
                    f"Unsupported authorization_mode: {request.authorization_mode}",
                    field_path="authorization_mode",
                )

        except Exception as exc:
            return None, map_index_exception_to_classified_error(exc)

