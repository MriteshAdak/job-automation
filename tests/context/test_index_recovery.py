"""Unit tests for startup and restart recovery in CONTEXT-03."""

from __future__ import annotations

import uuid
from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_files import (
    VECTORS_FILENAME,
    get_staging_dir,
)
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_recovery import IndexRecoveryManager
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_recovery_cleans_leftover_staging_directories(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    cand_id = uuid.uuid4()
    purpose = "assessment"

    # Simulate an interrupted build leaving a staging directory
    staging = get_staging_dir(indexes_dir, cand_id, purpose, uuid.uuid4())
    staging.mkdir(parents=True)
    (staging / "partial_file.tmp").write_bytes(b"unfinished")

    recovery = IndexRecoveryManager(indexes_dir=indexes_dir, repository=engine.context_indexes)
    report = recovery.reconcile(candidate_id=cand_id, purpose=purpose)

    assert len(report["staging_cleaned"]) == 1
    assert not staging.exists()


def test_recovery_detects_corrupt_active_generation(tmp_path: Path) -> None:
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
    recovery = IndexRecoveryManager(indexes_dir=indexes_dir, repository=engine.context_indexes)

    req = create_test_build_request(dimension=8)
    res, _ = builder.build(req)
    assert res is not None

    lifecycle.activate(req.candidate_id, req.purpose, res.generation_id)

    # Corrupt the vectors file
    final_dir = indexes_dir / str(req.candidate_id) / req.purpose / str(res.generation_id)
    (final_dir / VECTORS_FILENAME).write_bytes(b"tampered")

    # Reconcile detects corruption
    report = recovery.reconcile(candidate_id=req.candidate_id, purpose=req.purpose)
    assert not report["active_verified"]
    assert str(res.generation_id) in report["corrupt_generations"]

    # Status in database should be 'corrupt'
    gen_row = engine.context_indexes.get_generation(res.generation_id)
    assert gen_row is not None
    assert gen_row["status"] == "corrupt"

