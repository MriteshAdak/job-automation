"""Manifest builder for local retrieval index generations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from job_automation.context.index_identity import (
    compute_artifact_fingerprint,
    compute_embedding_space_fingerprint,
    compute_index_settings_fingerprint,
    compute_logical_build_fingerprint,
)
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.retrieval_index import (
    IndexBuildRequest,
    IndexManifest,
    IndexRowMapping,
    PayloadFileInfo,
)


class IndexManifestBuilder:
    """Constructs complete IndexManifest with deterministic fingerprints."""

    @staticmethod
    def build_manifest(
        generation_id: uuid.UUID,
        request: IndexBuildRequest,
        rows: Sequence[IndexRowMapping],
        payload_files: dict[str, PayloadFileInfo],
        created_at: UtcDatetime | None = None,
    ) -> IndexManifest:
        """Assemble and fingerprint IndexManifest."""
        now_utc = created_at or datetime.now(timezone.utc)
        emb_space_fp = compute_embedding_space_fingerprint(
            request.embedding_config, request.settings
        )
        settings_fp = compute_index_settings_fingerprint(request.settings)
        logical_fp = compute_logical_build_fingerprint(request, rows)
        artifact_fp = compute_artifact_fingerprint(logical_fp, payload_files)

        return IndexManifest(
            schema_version="1.0",
            manifest_version="v1",
            generation_id=generation_id,
            candidate_id=request.candidate_id,
            profile_version=request.profile_version,
            purpose=request.purpose,
            snapshot_fingerprint=request.chunk_set.snapshot_fingerprint,
            chunk_manifest_hash=request.chunk_set.manifest_fingerprint,
            inclusion_rule_version=request.chunk_set.inclusion_rule_version,
            chunking_version=request.chunk_set.chunking_version,
            embedding_configuration=request.embedding_config,
            embedding_space_fingerprint=emb_space_fp,
            index_settings=request.settings,
            settings_fingerprint=settings_fp,
            row_count=len(rows),
            dimension=request.embedding_config.dimension,
            rows=list(rows),
            payload_files=payload_files,
            logical_build_fingerprint=logical_fp,
            artifact_fingerprint=artifact_fp,
            created_at=now_utc,
        )
