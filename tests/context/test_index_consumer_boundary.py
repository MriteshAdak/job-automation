"""Tests demonstrating downstream consumer interaction at the IndexStore / IndexHandle boundary."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_reader import IndexStore
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_downstream_retrieval_consumer_flow(tmp_path: Path) -> None:
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

    # Consumer boundary
    read_req = IndexReadRequest(
        candidate_id=req.candidate_id,
        purpose=req.purpose,
        expected_profile_version=req.profile_version,
    )

    handle, err = store.open(read_req)
    assert err is None
    assert handle is not None

    with handle:
        # 1. Keyword search primitive
        postings = handle.lookup_terms(["c++", "münchen"])
        assert len(postings["c++"]) > 0
        matching_row = postings["c++"][0].row_ordinal

        # 2. Vector retrieval primitive
        row_vector = handle.get_vector(matching_row)
        assert len(row_vector) == 8

        # 3. Provenance and C08 evidence citation primitive
        chunk = handle.get_chunk(matching_row)
        assert chunk.title == "Senior C++ Software Engineer"
        assert len(chunk.sources) > 0
        assert chunk.sources[0].reference.fact_id == chunk.primary_fact_id

