"""Stable identity generation, version hashing, and canonical fingerprinting for retrieval indexes."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRequest,
    IndexRowMapping,
    IndexSettings,
    PayloadFileInfo,
)

INDEX_IDENTITY_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS, "context.index.job-automation.local"
)


def _canonical_json(data: Any) -> str:
    """Serialize data into deterministic, sorted-key, UTF-8 unescaped JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON."""
    canonical = _canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_embedding_space_fingerprint(
    config: EmbeddingConfiguration,
    settings: IndexSettings,
) -> str:
    """Compute deterministic SHA-256 fingerprint defining vector space compatibility.

    Covers:
    - Model identifier
    - Dimension
    - Model digest (or expected digest)
    - Document and query prefix rules
    - Runtime and provider versions
    - Output-affecting options
    - Matrix dtype, byte order, metric, and normalization
    """
    digest_val = config.model_digest or config.expected_digest or "unverified"
    payload = {
        "fingerprint_version": "v1",
        "model_identifier": config.model_identifier,
        "dimension": config.dimension,
        "model_digest": digest_val,
        "document_prefix": config.document_prefix,
        "query_prefix": config.query_prefix,
        "runtime_version": config.runtime_version,
        "provider_version": config.provider_version,
        "output_affecting_options": config.output_affecting_options,
        "dtype": settings.dtype,
        "byte_order": settings.byte_order,
        "metric": settings.metric,
        "normalization": settings.normalization,
    }
    return _sha256_hex(payload)


def compute_index_settings_fingerprint(settings: IndexSettings) -> str:
    """Compute deterministic SHA-256 fingerprint over semantic index settings."""
    payload = {
        "fingerprint_version": "v1",
        "index_version": settings.index_version,
        "algorithm_version": settings.algorithm_version,
        "format_version": settings.format_version,
        "canonicalization_version": settings.canonicalization_version,
        "dtype": settings.dtype,
        "byte_order": settings.byte_order,
        "metric": settings.metric,
        "normalization": settings.normalization,
        "analyzer_version": settings.analyzer_version,
        "analyzer_options": settings.analyzer_options,
        "max_chunks": settings.max_chunks,
        "max_dimension": settings.max_dimension,
        "max_text_bytes": settings.max_text_bytes,
    }
    return _sha256_hex(payload)


def compute_logical_build_fingerprint(
    request: IndexBuildRequest,
    rows: Sequence[IndexRowMapping],
) -> str:
    """Compute deterministic SHA-256 logical fingerprint of complete frozen inputs.

    Explicitly excludes:
    - Generation UUID
    - Timestamps
    - File paths
    - Embedding call IDs and latencies
    """
    emb_space = compute_embedding_space_fingerprint(request.embedding_config, request.settings)
    settings_fp = compute_index_settings_fingerprint(request.settings)

    row_projections = [
        {
            "row_ordinal": r.row_ordinal,
            "chunk_id": str(r.chunk_id),
            "chunk_version": r.chunk_version,
            "binding_fingerprint": r.binding_fingerprint,
            "primary_fact_id": str(r.primary_fact_id),
            "primary_kind": str(r.primary_kind),
        }
        for r in rows
    ]

    payload = {
        "candidate_id": str(request.candidate_id),
        "profile_version": request.profile_version,
        "purpose": request.purpose,
        "snapshot_fingerprint": request.chunk_set.snapshot_fingerprint,
        "chunk_manifest_hash": request.chunk_set.manifest_fingerprint,
        "embedding_space_fingerprint": emb_space,
        "settings_fingerprint": settings_fp,
        "rows": row_projections,
    }
    return _sha256_hex(payload)


def compute_artifact_fingerprint(
    logical_build_fingerprint: str,
    payload_files: dict[str, PayloadFileInfo],
) -> str:
    """Compute deterministic SHA-256 digest covering logical build and physical payload hashes."""
    sorted_files = sorted(
        [
            {
                "key": k,
                "relative_path": info.relative_path,
                "byte_length": info.byte_length,
                "sha256_hash": info.sha256_hash,
            }
            for k, info in payload_files.items()
        ],
        key=lambda item: item["key"],
    )
    payload = {
        "logical_build_fingerprint": logical_build_fingerprint,
        "payload_files": sorted_files,
    }
    return _sha256_hex(payload)


def validate_embedding_space_compatibility(
    config_a: EmbeddingConfiguration,
    config_b: EmbeddingConfiguration,
    settings: IndexSettings,
) -> bool:
    """Return True if both configurations define an identical, compatible embedding space."""
    fp_a = compute_embedding_space_fingerprint(config_a, settings)
    fp_b = compute_embedding_space_fingerprint(config_b, settings)
    return fp_a == fp_b

