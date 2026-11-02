"""Unit tests for index diagnostics, status inspection, and safe error reporting."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_errors import (
    IndexCapacityError,
    IndexIncompatibleError,
    map_index_exception_to_classified_error,
)
from job_automation.context.index_service import IndexService
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_build_request
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_index_service_status_and_verify(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    service = IndexService(
        indexes_dir=indexes_dir,
        repository=engine.context_indexes,
        provider=provider,
    )

    req = create_test_build_request(dimension=8)

    # Initial status: no active index
    stat0 = service.status(req.candidate_id, req.purpose)
    assert not stat0["has_active"]

    # Build and auto-activate
    res, err = service.build(req, auto_activate=True)
    assert err is None
    assert res is not None

    # Status after build
    stat1 = service.status(req.candidate_id, req.purpose)
    assert stat1["has_active"]
    assert stat1["active_generation_id"] == str(res.generation_id)
    assert stat1["active_row_count"] == len(req.chunk_set.chunks)
    assert stat1["active_dimension"] == 8

    # Verify active payload files
    ok, msg = service.verify(req.candidate_id, req.purpose)
    assert ok
    assert "verified on disk" in msg


def test_safe_error_diagnostics_no_secret_leak() -> None:
    secret_text = "SECRET_CANDIDATE_DATA_DO_NOT_LOG"
    exc = IndexCapacityError(
        message=f"Chunk retrieval_text exceeded capacity limit",
        field_path="chunk_set.chunks[0].retrieval_text",
        details={"bytes": 70000, "limit": 65536},
    )

    classified = map_index_exception_to_classified_error(exc)
    err_str = str(classified.model_dump())
    assert secret_text not in err_str

