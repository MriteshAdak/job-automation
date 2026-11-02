"""Unit tests for ContextIndexRepository persistence and compare-and-swap operations."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.index_manifest import IndexManifestBuilder
from job_automation.contracts.primitives import UtcDatetime
from job_automation.contracts.retrieval_index import (
    IndexBuildRecord,
    IndexRowMapping,
    PayloadFileInfo,
)
from job_automation.storage.connection import open_connection
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError, StorageError
from tests.context.index_test_helpers import (
    create_test_build_request,
    create_test_chunk_set,
)


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test_storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()
    return engine


def test_save_and_get_generation(storage: StorageEngine, tmp_path: Path) -> None:
    repo = storage.context_indexes
    req = create_test_build_request()
    gen_id = uuid.uuid4()

    files = {
        "vectors": PayloadFileInfo(relative_path="vectors.bin", byte_length=100, sha256_hash="a" * 64),
        "keywords": PayloadFileInfo(relative_path="keywords.db", byte_length=200, sha256_hash="b" * 64),
        "chunks": PayloadFileInfo(relative_path="chunks.json", byte_length=300, sha256_hash="c" * 64),
    }
    rows = [
        IndexRowMapping(
            row_ordinal=0,
            chunk_id=req.chunk_set.chunks[0].chunk_id,
            chunk_version=req.chunk_set.chunks[0].chunk_version,
            binding_fingerprint=req.chunk_set.chunks[0].binding_fingerprint,
            primary_fact_id=req.chunk_set.chunks[0].primary_fact_id,
            primary_kind=req.chunk_set.chunks[0].primary_kind,
        )
    ]
    manifest = IndexManifestBuilder.build_manifest(gen_id, req, rows, files)
    gen_dir = tmp_path / "gen_dir"

    repo.save_generation(manifest, gen_dir, status="ready")

    loaded = repo.get_generation(gen_id)
    assert loaded is not None
    assert loaded["generation_id"] == str(gen_id)
    assert loaded["status"] == "ready"
    assert loaded["profile_version"] == req.profile_version

    # Duplicate key rejection
    with pytest.raises(DuplicateKeyError):
        repo.save_generation(manifest, gen_dir, status="ready")


def test_activation_and_conflict_handling(storage: StorageEngine, tmp_path: Path) -> None:
    repo = storage.context_indexes
    cand_id = uuid.uuid4()
    req = create_test_build_request()
    req = req.model_copy(update={"candidate_id": cand_id})

    # Create Generation 1
    gen1_id = uuid.uuid4()
    files = {"vectors": PayloadFileInfo(relative_path="vectors.bin", byte_length=10, sha256_hash="1" * 64)}
    m1 = IndexManifestBuilder.build_manifest(gen1_id, req, [], files)
    repo.save_generation(m1, tmp_path / "gen1", status="ready")

    # Activate Gen 1
    token1 = "token-111"
    repo.set_active_generation(
        candidate_id=cand_id,
        purpose=req.purpose,
        generation_id=gen1_id,
        profile_version=req.profile_version,
        activation_token=token1,
    )

    active = repo.get_active_generation(cand_id, req.purpose)
    assert active is not None
    assert active["active_generation_id"] == str(gen1_id)
    assert active["activation_token"] == token1

    # Create Generation 2
    gen2_id = uuid.uuid4()
    m2 = IndexManifestBuilder.build_manifest(gen2_id, req, [], files)
    repo.save_generation(m2, tmp_path / "gen2", status="ready")

    # Activation with WRONG expected prior token raises StorageError
    with pytest.raises(StorageError) as exc:
        repo.set_active_generation(
            candidate_id=cand_id,
            purpose=req.purpose,
            generation_id=gen2_id,
            profile_version=req.profile_version,
            activation_token="token-222",
            expected_prior_token="wrong-token",
        )
    assert "token conflict" in str(exc.value)

    # Activation with correct expected prior token succeeds
    token2 = "token-222"
    repo.set_active_generation(
        candidate_id=cand_id,
        purpose=req.purpose,
        generation_id=gen2_id,
        profile_version=req.profile_version,
        activation_token=token2,
        expected_prior_token=token1,
    )

    # Gen 1 should now be retired, Gen 2 active
    gen1_row = repo.get_generation(gen1_id)
    assert gen1_row is not None
    assert gen1_row["status"] == "retired"

    active2 = repo.get_active_generation(cand_id, req.purpose)
    assert active2 is not None
    assert active2["active_generation_id"] == str(gen2_id)
    assert active2["activation_token"] == token2


def test_pinning_operations(storage: StorageEngine, tmp_path: Path) -> None:
    repo = storage.context_indexes
    req = create_test_build_request()
    gen_id = uuid.uuid4()
    files = {"v": PayloadFileInfo(relative_path="v", byte_length=1, sha256_hash="0" * 64)}
    m = IndexManifestBuilder.build_manifest(gen_id, req, [], files)
    repo.save_generation(m, tmp_path / "g", status="ready")

    assert not repo.is_generation_pinned(gen_id)

    pin_id = repo.pin_generation(gen_id, pinned_for="reader", pinned_by="worker-1")
    assert repo.is_generation_pinned(gen_id)

    repo.release_pin(pin_id)
    assert not repo.is_generation_pinned(gen_id)

