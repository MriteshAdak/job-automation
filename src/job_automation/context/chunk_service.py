"""Public offline evidence chunking service for CONTEXT-02."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_changes import compare_chunk_manifests
from job_automation.context.chunk_errors import (
    ChunkBindingError,
    map_chunk_exception_to_classified_error,
)
from job_automation.context.chunk_manifest import ChunkManifestBuilder
from job_automation.context.chunk_preparation import ChunkEvidencePreparer
from job_automation.context.chunk_validity import validate_chunk_binding
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.evidence_chunks import (
    ChunkBuildRequest,
    ChunkChangeSet,
    ChunkSet,
    EvidenceChunk,
)


class EvidenceChunker:
    """Public offline service for deterministic evidence chunk creation and invalidation."""

    def __init__(
        self,
        preparer: ChunkEvidencePreparer | None = None,
        builder: ChunkBuilder | None = None,
    ) -> None:
        self.preparer = preparer or ChunkEvidencePreparer()
        self.builder = builder or ChunkBuilder()

    def build(
        self, request: ChunkBuildRequest
    ) -> tuple[ChunkSet | None, ClassifiedError | None]:
        """Construct deterministic ChunkSet from approved snapshot or return safe ClassifiedError.

        Invariant: Exactly one of (chunk_set, error) is non-null.
        """
        try:
            # 1. Prepare permitted evidence and ancestor chains
            prep_data = self.preparer.prepare(
                snapshot=request.snapshot,
                purpose=request.purpose,
                settings=request.settings,
                explicit_required_fact_ids=request.explicit_required_fact_ids,
            )

            # 2. Build individual evidence chunks
            chunks: list[EvidenceChunk] = []
            for p_fact in prep_data.prepared_facts:
                chunk = self.builder.build_chunk(
                    candidate_id=request.snapshot.candidate_id,
                    profile_version=request.snapshot.profile_version,
                    purpose=request.purpose,
                    prepared_fact=p_fact,
                    settings=request.settings,
                )
                chunks.append(chunk)

            # 3. Assemble and verify complete manifest
            manifest = ChunkManifestBuilder.build_manifest(
                snapshot=request.snapshot,
                purpose=request.purpose,
                settings=request.settings,
                chunks=chunks,
                eligible_fact_ids=prep_data.eligible_fact_ids,
                excluded_fact_count=prep_data.excluded_fact_count,
                warnings=prep_data.warnings,
            )

            return manifest, None

        except Exception as exc:
            classified = map_chunk_exception_to_classified_error(exc)
            return None, classified

    def diff(
        self,
        base_manifest: ChunkSet | None,
        target_manifest: ChunkSet,
    ) -> tuple[ChunkChangeSet | None, ClassifiedError | None]:
        """Compare base and target manifests to produce deterministic invalidation changes.

        Invariant: Exactly one of (change_set, error) is non-null.
        """
        try:
            change_set = compare_chunk_manifests(
                base_manifest=base_manifest,
                target_manifest=target_manifest,
            )
            return change_set, None
        except Exception as exc:
            classified = map_chunk_exception_to_classified_error(exc)
            return None, classified

    def validate_binding(
        self,
        chunk_set: ChunkSet,
        expected_candidate_id: uuid.UUID,
        expected_profile_version: str,
        expected_purpose: str,
        expected_settings_fingerprint: str | None = None,
    ) -> tuple[bool, ClassifiedError | None]:
        """Verify that a manifest satisfies exact caller binding requirements.

        Invariant: Exactly one of (True, None) or (False, error) is returned.
        """
        valid, msg = validate_chunk_binding(
            chunk_set=chunk_set,
            expected_candidate_id=expected_candidate_id,
            expected_profile_version=expected_profile_version,
            expected_purpose=expected_purpose,
            expected_settings_fingerprint=expected_settings_fingerprint,
        )
        if not valid:
            classified = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=msg or "Manifest binding validation failed",
                field_path="binding",
                details={
                    "candidate_id": str(expected_candidate_id),
                    "profile_version": expected_profile_version,
                    "purpose": expected_purpose,
                },
            )
            return False, classified

        return True, None

