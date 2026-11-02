"""Manifest construction and coverage verification for CONTEXT-02 ChunkSet."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.chunk_errors import ChunkValidationError
from job_automation.context.chunk_identity import (
    compute_manifest_fingerprint,
    compute_settings_fingerprint,
    compute_snapshot_fingerprint,
)
from job_automation.contracts.evidence_chunks import (
    ChunkSet,
    ChunkingSettings,
    EvidenceChunk,
)
from job_automation.contracts.profile import ProfileSnapshot


class ChunkManifestBuilder:
    """Assembles and verifies complete ChunkSet manifests."""

    @staticmethod
    def build_manifest(
        snapshot: ProfileSnapshot,
        purpose: str,
        settings: ChunkingSettings,
        chunks: Sequence[EvidenceChunk],
        eligible_fact_ids: Sequence[uuid.UUID],
        excluded_fact_count: int,
        warnings: Sequence[str],
    ) -> ChunkSet:
        """Assemble a verified, deterministic ChunkSet manifest."""
        coverage_fact_ids = [c.primary_fact_id for c in chunks]

        # Invariant: Coverage of every eligible fact
        if set(coverage_fact_ids) != set(eligible_fact_ids):
            missing = set(eligible_fact_ids) - set(coverage_fact_ids)
            extra = set(coverage_fact_ids) - set(eligible_fact_ids)
            raise ChunkValidationError(
                f"Chunk coverage mismatch: missing={list(missing)}, extra={list(extra)}",
                field_path="coverage_fact_ids",
            )

        # Invariant: Chunk ordering matches eligible_fact_ids ordering
        if coverage_fact_ids != list(eligible_fact_ids):
            raise ChunkValidationError(
                "Chunk order does not match shared eligible fact order",
                field_path="chunks",
            )

        snapshot_fingerprint = compute_snapshot_fingerprint(snapshot)
        settings_fingerprint = compute_settings_fingerprint(settings)
        chunk_binding_fingerprints = [c.binding_fingerprint for c in chunks]

        manifest_fingerprint = compute_manifest_fingerprint(
            candidate_id=snapshot.candidate_id,
            profile_version=snapshot.profile_version,
            purpose=purpose,
            snapshot_fingerprint=snapshot_fingerprint,
            inclusion_rule_version="v1",
            chunking_version=settings.algorithm_version,
            settings_fingerprint=settings_fingerprint,
            chunk_binding_fingerprints=chunk_binding_fingerprints,
            eligible_fact_ids=eligible_fact_ids,
            coverage_fact_ids=coverage_fact_ids,
            excluded_fact_count=excluded_fact_count,
            warnings=warnings,
        )

        return ChunkSet(
            candidate_id=snapshot.candidate_id,
            profile_version=snapshot.profile_version,
            purpose=purpose,
            snapshot_fingerprint=snapshot_fingerprint,
            inclusion_rule_version="v1",
            chunking_version=settings.algorithm_version,
            settings_fingerprint=settings_fingerprint,
            chunks=list(chunks),
            eligible_fact_ids=list(eligible_fact_ids),
            coverage_fact_ids=coverage_fact_ids,
            excluded_fact_count=excluded_fact_count,
            warnings=list(warnings),
            manifest_fingerprint=manifest_fingerprint,
        )

