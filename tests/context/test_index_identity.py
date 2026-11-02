"""Unit tests for canonical fingerprinting and identity derivation in CONTEXT-03."""

from __future__ import annotations

import uuid

from job_automation.context.index_identity import (
    compute_artifact_fingerprint,
    compute_embedding_space_fingerprint,
    compute_index_settings_fingerprint,
    compute_logical_build_fingerprint,
)
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.retrieval_index import (
    IndexRowMapping,
    PayloadFileInfo,
)
from tests.context.index_test_helpers import (
    create_test_build_request,
    create_test_embedding_config,
    create_test_index_settings,
)


def test_embedding_space_fingerprint_sensitivity() -> None:
    settings = create_test_index_settings()
    cfg1 = create_test_embedding_config(dimension=8, model_identifier="model-a")
    cfg2 = create_test_embedding_config(dimension=8, model_identifier="model-b")

    fp1 = compute_embedding_space_fingerprint(cfg1, settings)
    fp2 = compute_embedding_space_fingerprint(cfg2, settings)

    # Different model identifier must produce different embedding space fingerprint
    assert fp1 != fp2

    # Changed dimension produces different fingerprint
    cfg3 = create_test_embedding_config(dimension=16, model_identifier="model-a")
    fp3 = compute_embedding_space_fingerprint(cfg3, settings)
    assert fp1 != fp3

    # Changed prefix produces different fingerprint
    cfg4 = cfg1.model_copy(update={"document_prefix": "doc: "})
    fp4 = compute_embedding_space_fingerprint(cfg4, settings)
    assert fp1 != fp4

    # Identical configuration reproduces exact same fingerprint
    fp1_recomputed = compute_embedding_space_fingerprint(cfg1, settings)
    assert fp1 == fp1_recomputed


def test_logical_build_fingerprint_reproducibility() -> None:
    req1 = create_test_build_request()
    rows1 = [
        IndexRowMapping(
            row_ordinal=idx,
            chunk_id=c.chunk_id,
            chunk_version=c.chunk_version,
            binding_fingerprint=c.binding_fingerprint,
            primary_fact_id=c.primary_fact_id,
            primary_kind=c.primary_kind,
        )
        for idx, c in enumerate(req1.chunk_set.chunks)
    ]

    fp1 = compute_logical_build_fingerprint(req1, rows1)

    # Exact same inputs produce identical logical build fingerprint
    fp2 = compute_logical_build_fingerprint(req1, rows1)
    assert fp1 == fp2

    # Changed chunk version changes fingerprint
    mutated_rows = [
        rows1[0].model_copy(update={"chunk_version": "tampered_version"}),
        *rows1[1:],
    ]
    fp_mutated = compute_logical_build_fingerprint(req1, mutated_rows)
    assert fp1 != fp_mutated


def test_artifact_fingerprint_covers_all_payload_files() -> None:
    logical_fp = "logical_fingerprint_123"
    files1 = {
        "vectors": PayloadFileInfo(relative_path="vectors.bin", byte_length=100, sha256_hash="a" * 64),
        "keywords": PayloadFileInfo(relative_path="keywords.db", byte_length=200, sha256_hash="b" * 64),
    }

    art_fp1 = compute_artifact_fingerprint(logical_fp, files1)

    # Changing a file hash changes the artifact fingerprint
    files2 = {
        "vectors": PayloadFileInfo(relative_path="vectors.bin", byte_length=100, sha256_hash="c" * 64),
        "keywords": PayloadFileInfo(relative_path="keywords.db", byte_length=200, sha256_hash="b" * 64),
    }
    art_fp2 = compute_artifact_fingerprint(logical_fp, files2)
    assert art_fp1 != art_fp2

