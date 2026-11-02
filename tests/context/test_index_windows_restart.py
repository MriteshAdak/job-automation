"""Tests verifying index payload reopen and state preservation across process restarts."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_reader import IndexStore
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_index_state_and_read_across_restart(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"

    # 1. First process: build and activate
    engine1 = StorageEngine(db_path=db_path)
    engine1.migrate()

    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=provider,
        repository=engine1.context_indexes,
    )
    lifecycle = IndexLifecycleManager(repository=engine1.context_indexes)

    req = create_test_build_request(dimension=8)
    res, _ = builder.build(req)
    assert res is not None

    token = lifecycle.activate(req.candidate_id, req.purpose, res.generation_id)
    assert token is not None

    # Close first engine
    engine1.close()

    # 2. Second process (simulated): open new engine and read index
    engine2 = StorageEngine(db_path=db_path)
    store = IndexStore(indexes_dir=indexes_dir, repository=engine2.context_indexes)

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
        assert handle.manifest.generation_id == res.generation_id

        # Vectors and keyword lookups work seamlessly across restart
        vec0 = handle.get_vector(0)
        assert len(vec0) == 8
        hits = handle.lookup_term("c++")
        assert len(hits) > 0
    finally:
        handle.close()
        engine2.close()

