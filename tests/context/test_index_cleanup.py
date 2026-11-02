"""Unit tests for retired index payload cleanup and retention policy in CONTEXT-03."""

from __future__ import annotations

import uuid
from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_cleanup import IndexCleanupManager
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_cleanup_respects_retention_and_pins(tmp_path: Path) -> None:
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
    cleanup = IndexCleanupManager(repository=engine.context_indexes, default_retention_count=1)

    req = create_test_build_request(dimension=8)

    # Build and activate Gen 1
    res1, _ = builder.build(req)
    assert res1 is not None
    tok1 = lifecycle.activate(req.candidate_id, req.purpose, res1.generation_id)

    # Pin Gen 1 (e.g. active reader or frozen task)
    pin_id = engine.context_indexes.pin_generation(
        res1.generation_id, pinned_for="frozen_task", pinned_by="worker"
    )

    # Build and activate Gen 2
    res2, _ = builder.build(req)
    assert res2 is not None
    tok2 = lifecycle.activate(
        req.candidate_id, req.purpose, res2.generation_id, expected_prior_token=tok1
    )

    # Build and activate Gen 3
    res3, _ = builder.build(req)
    assert res3 is not None
    tok3 = lifecycle.activate(
        req.candidate_id, req.purpose, res3.generation_id, expected_prior_token=tok2
    )

    # Gen 1 is retired but PINNED
    # Gen 2 is retired and UNPINNED
    # Gen 3 is ACTIVE
    rep = cleanup.cleanup(req.candidate_id, req.purpose, retention_count=0)

    # Gen 1 must be pinned, not deleted
    assert str(res1.generation_id) in rep["pinned"]

    # Gen 2 must be deleted
    assert str(res2.generation_id) in rep["deleted"]
    dir_gen2 = indexes_dir / str(req.candidate_id) / req.purpose / str(res2.generation_id)
    assert not dir_gen2.exists()

    # Active Gen 3 must remain intact
    dir_gen3 = indexes_dir / str(req.candidate_id) / req.purpose / str(res3.generation_id)
    assert dir_gen3.exists()

    # Release pin on Gen 1
    engine.context_indexes.release_pin(pin_id)
    rep2 = cleanup.cleanup(req.candidate_id, req.purpose, retention_count=0)
    assert str(res1.generation_id) in rep2["deleted"]
    dir_gen1 = indexes_dir / str(req.candidate_id) / req.purpose / str(res1.generation_id)
    assert not dir_gen1.exists()

