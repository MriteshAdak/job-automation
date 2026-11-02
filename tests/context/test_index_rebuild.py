"""Unit tests verifying reproducible rebuild behavior in CONTEXT-03."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_reproducible_rebuild_from_identical_inputs(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(indexes_dir=indexes_dir, provider=provider)

    req = create_test_build_request(dimension=8)

    # First build
    res1, err1 = builder.build(req)
    assert err1 is None
    assert res1 is not None

    # Second build from identical inputs
    res2, err2 = builder.build(req)
    assert err2 is None
    assert res2 is not None

    # Generation IDs are unique
    assert res1.generation_id != res2.generation_id

    # Logical build fingerprints MUST be identical
    assert res1.manifest.logical_build_fingerprint == res2.manifest.logical_build_fingerprint

    # Vector payload hashes MUST be identical
    vec_hash_1 = res1.manifest.payload_files["vectors"].sha256_hash
    vec_hash_2 = res2.manifest.payload_files["vectors"].sha256_hash
    assert vec_hash_1 == vec_hash_2

    # Chunk payload hashes MUST be identical
    chk_hash_1 = res1.manifest.payload_files["chunks"].sha256_hash
    chk_hash_2 = res2.manifest.payload_files["chunks"].sha256_hash
    assert chk_hash_1 == chk_hash_2

    # Row mappings must match 1:1
    assert len(res1.manifest.rows) == len(res2.manifest.rows)
    for r1, r2 in zip(res1.manifest.rows, res2.manifest.rows):
        assert r1.chunk_id == r2.chunk_id
        assert r1.chunk_version == r2.chunk_version
        assert r1.binding_fingerprint == r2.binding_fingerprint

