"""Unit tests for IndexStore opening and IndexHandle read operations."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_errors import IndexIncompatibleError
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_reader import IndexStore
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_index_store_open_current_use_success(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=provider,
        repository=engine.context_indexes,
    )
    lifecycle = IndexLifecycleManager(repository=engine.context_indexes)
    store = IndexStore(indexes_dir=indexes_dir, repository=engine.context_indexes)

    req = create_test_build_request(dimension=8)
    res, _ = builder.build(req)
    assert res is not None

    lifecycle.activate(req.candidate_id, req.purpose, res.generation_id)

    read_req = IndexReadRequest(
        candidate_id=req.candidate_id,
        purpose=req.purpose,
        expected_profile_version=req.profile_version,
    )
    handle, err = store.open(read_req)
    assert err is None
    assert handle is not None

    try:
        assert handle.row_count == len(req.chunk_set.chunks)
        assert handle.dimension == 8

        # Valid query embedding space passes
        handle.validate_query_embedding_space(handle.manifest.embedding_space_fingerprint)

        # Incompatible query embedding space raises IndexIncompatibleError
        with pytest.raises(IndexIncompatibleError):
            handle.validate_query_embedding_space("incompatible_query_space")
    finally:
        handle.close()

    # Reading after close raises ValueError
    with pytest.raises(ValueError):
        handle.get_vector(0)


def test_index_store_rejects_stale_profile_version(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=provider,
        repository=engine.context_indexes,
    )
    lifecycle = IndexLifecycleManager(repository=engine.context_indexes)
    store = IndexStore(indexes_dir=indexes_dir, repository=engine.context_indexes)

    req = create_test_build_request(dimension=8)
    res, _ = builder.build(req)
    assert res is not None
    lifecycle.activate(req.candidate_id, req.purpose, res.generation_id)

    read_req = IndexReadRequest(
        candidate_id=req.candidate_id,
        purpose=req.purpose,
        expected_profile_version="v999",  # Stale!
    )
    handle, err = store.open(read_req)
    assert handle is None
    assert err is not None
    assert err.category == ErrorCategory.VALIDATION

