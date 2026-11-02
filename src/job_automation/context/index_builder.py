"""Local vector and keyword index builder orchestrating construction and persistence."""

from __future__ import annotations

import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from job_automation.context.index_capacity import (
    check_index_capacity_preflight,
    validate_index_path,
)
from job_automation.context.index_embeddings import IndexEmbeddingCoordinator
from job_automation.context.index_errors import (
    map_index_exception_to_classified_error,
)
from job_automation.context.index_files import (
    CHUNKS_FILENAME,
    KEYWORDS_FILENAME,
    MANIFEST_FILENAME,
    VECTORS_FILENAME,
    compute_file_digest,
    finalize_staging_directory,
    get_generation_dir,
    get_staging_dir,
    verify_generation_files,
)
from job_automation.context.index_manifest import IndexManifestBuilder
from job_automation.context.index_ports import IndexBuilderPort
from job_automation.context.index_serialization import (
    write_chunks_file,
    write_manifest_file,
)
from job_automation.context.keyword_index import KeywordIndexWriter
from job_automation.context.vector_matrix import VectorMatrixWriter
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.retrieval_index import (
    IndexBuildRecord,
    IndexBuildRequest,
    IndexBuildResult,
    IndexRowMapping,
    PayloadFileInfo,
)
from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexBuilder(IndexBuilderPort):
    """Constructs local vector matrix and keyword index from a CONTEXT-02 ChunkSet."""

    def __init__(
        self,
        indexes_dir: Path | str,
        provider: ModelProvider,
        repository: ContextIndexRepository | None = None,
    ) -> None:
        self.indexes_dir = Path(indexes_dir)
        self.provider = provider
        self.repository = repository

    def build(
        self,
        request: IndexBuildRequest,
    ) -> tuple[IndexBuildResult | None, ClassifiedError | None]:
        """Build local vector and keyword indexes for the given request.

        Invariant: Exactly one of (result, error) is non-null.
        """
        build_id = uuid.uuid4()
        generation_id = uuid.uuid4()
        start_mono = time.monotonic()
        started_at = datetime.now(timezone.utc)

        staging_dir: Path | None = None
        final_dir: Path | None = None

        try:
            # 1. Preflight capacity check
            check_index_capacity_preflight(
                chunk_set=request.chunk_set,
                config=request.embedding_config,
                settings=request.settings,
                destination_dir=self.indexes_dir,
            )

            # 2. Setup generation & staging paths
            staging_dir = get_staging_dir(
                self.indexes_dir, request.candidate_id, request.purpose, generation_id
            )
            final_dir = get_generation_dir(
                self.indexes_dir, request.candidate_id, request.purpose, generation_id
            )

            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            staging_dir.mkdir(parents=True, exist_ok=True)

            # 3. Build ordered row mappings aligned 1:1 with input chunks
            rows: list[IndexRowMapping] = []
            for row_idx, chunk in enumerate(request.chunk_set.chunks):
                row_map = IndexRowMapping(
                    row_ordinal=row_idx,
                    chunk_id=chunk.chunk_id,
                    chunk_version=chunk.chunk_version,
                    binding_fingerprint=chunk.binding_fingerprint,
                    primary_fact_id=chunk.primary_fact_id,
                    primary_kind=chunk.primary_kind,
                    c08_references=[src.reference for src in chunk.sources],
                    parent_fact_ids=[anc.fact_id for anc in chunk.ancestor_context],
                )
                rows.append(row_map)

            # 4. Generate embeddings through LLM-01 ModelProvider
            coordinator = IndexEmbeddingCoordinator(
                provider=self.provider,
                config=request.embedding_config,
                settings=request.settings,
            )
            vectors, call_ids, total_input_bytes = coordinator.embed_chunks(
                request.chunk_set.chunks
            )

            # 5. Write binary vector matrix
            matrix_writer = VectorMatrixWriter(
                dest_path=staging_dir / VECTORS_FILENAME,
                dimension=request.embedding_config.dimension,
                dtype=request.settings.dtype,
                byte_order=request.settings.byte_order,
            )
            vectors_info = matrix_writer.write_matrix(vectors, relative_to=staging_dir)

            # 6. Write keyword postings database
            kw_writer = KeywordIndexWriter(db_path=staging_dir / KEYWORDS_FILENAME)
            row_texts = [c.retrieval_text for c in request.chunk_set.chunks]
            kw_info = kw_writer.build_index(
                row_texts=row_texts,
                metadata={
                    "generation_id": str(generation_id),
                    "candidate_id": str(request.candidate_id),
                    "profile_version": request.profile_version,
                    "purpose": request.purpose,
                },
                relative_to=staging_dir,
            )

            # 7. Write canonical exported chunks
            chunks_path = staging_dir / CHUNKS_FILENAME
            write_chunks_file(request.chunk_set.chunks, chunks_path)
            chunks_info = compute_file_digest(chunks_path, relative_to=staging_dir)

            # 8. Assemble and write IndexManifest
            payload_files = {
                "vectors": vectors_info,
                "keywords": kw_info,
                "chunks": chunks_info,
            }
            manifest = IndexManifestBuilder.build_manifest(
                generation_id=generation_id,
                request=request,
                rows=rows,
                payload_files=payload_files,
                created_at=datetime.now(timezone.utc),
            )
            manifest_path = staging_dir / MANIFEST_FILENAME
            write_manifest_file(manifest, manifest_path)

            # 9. Atomically promote staging directory to final immutable generation directory
            finalize_staging_directory(staging_dir, final_dir)

            # 10. Verify payload files and hashes on finalized directory
            verify_generation_files(final_dir, manifest)

            # 11. Calculate build metrics
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            completed_at = datetime.now(timezone.utc)
            total_payload_bytes = sum(f.byte_length for f in payload_files.values())
            activation_token = str(uuid.uuid4())

            build_record = IndexBuildRecord(
                build_id=build_id,
                generation_id=generation_id,
                candidate_id=request.candidate_id,
                profile_version=request.profile_version,
                purpose=request.purpose,
                status="completed",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                chunk_count=len(rows),
                vector_count=len(vectors),
                term_count=len(rows),  # Approximate distinct terms counted by postings
                embedding_call_ids=call_ids,
                total_input_bytes=total_input_bytes,
                payload_bytes=total_payload_bytes,
                logical_build_fingerprint=manifest.logical_build_fingerprint,
                artifact_fingerprint=manifest.artifact_fingerprint,
                is_verified=True,
            )

            # 12. Persist generation and build records to repository if configured
            if self.repository is not None:
                self.repository.save_generation(manifest, final_dir, status="ready")
                self.repository.save_build_record(build_record)

            result = IndexBuildResult(
                generation_id=generation_id,
                manifest=manifest,
                build_record=build_record,
                activation_token=activation_token,
            )
            return result, None

        except Exception as exc:
            # Clean up staging directory on failure
            if staging_dir is not None and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

            duration_ms = (time.monotonic() - start_mono) * 1000.0
            completed_at = datetime.now(timezone.utc)
            classified_err = map_index_exception_to_classified_error(exc)

            if self.repository is not None:
                failed_record = IndexBuildRecord(
                    build_id=build_id,
                    generation_id=generation_id,
                    candidate_id=request.candidate_id,
                    profile_version=request.profile_version,
                    purpose=request.purpose,
                    status="failed",
                    started_at=started_at,
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    chunk_count=len(request.chunk_set.chunks),
                    vector_count=0,
                    term_count=0,
                    embedding_call_ids=[],
                    total_input_bytes=0,
                    payload_bytes=0,
                    logical_build_fingerprint="failed",
                    error=classified_err,
                    is_verified=False,
                )
                try:
                    self.repository.save_build_record(failed_record)
                except Exception:
                    pass

            return None, classified_err
