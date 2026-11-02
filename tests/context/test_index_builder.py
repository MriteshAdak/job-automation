"""Unit tests for IndexBuilder end-to-end construction."""

from __future__ import annotations

from pathlib import Path

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_files import (
    CHUNKS_FILENAME,
    KEYWORDS_FILENAME,
    MANIFEST_FILENAME,
    VECTORS_FILENAME,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import (
    create_test_build_request,
    create_test_chunk_set,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_index_builder_build_success(tmp_path: Path) -> None:
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

    req = create_test_build_request(dimension=8)
    result, err = builder.build(req)

    # Invariant: exactly one is non-null
    assert err is None
    assert result is not None

    assert result.generation_id is not None
    assert result.manifest.row_count == len(req.chunk_set.chunks)
    assert result.manifest.dimension == 8
    assert result.activation_token is not None

    # Check files exist on disk in the final directory
    final_dir = indexes_dir / str(req.candidate_id) / req.purpose / str(result.generation_id)
    assert (final_dir / MANIFEST_FILENAME).is_file()
    assert (final_dir / VECTORS_FILENAME).is_file()
    assert (final_dir / KEYWORDS_FILENAME).is_file()
    assert (final_dir / CHUNKS_FILENAME).is_file()

    # Check repository recorded the generation and build
    gen_row = engine.context_indexes.get_generation(result.generation_id)
    assert gen_row is not None
    assert gen_row["status"] == "ready"

    build_rec = engine.context_indexes.get_build_record(result.build_record.build_id)
    assert build_rec is not None
    assert build_rec.status == "completed"


def test_index_builder_empty_chunk_set(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    builder = IndexBuilder(indexes_dir=indexes_dir, provider=provider)

    from tests.context.index_test_helpers import create_test_profile_snapshot

    snap_empty = create_test_profile_snapshot(facts=[])
    cs = create_test_chunk_set(snap_empty)
    req = create_test_build_request(chunk_set=cs, dimension=8)

    result, err = builder.build(req)
    assert err is None
    assert result is not None
    assert result.manifest.row_count == 0
    assert result.manifest.dimension == 8


def test_index_builder_handles_provider_failure_cleanly(tmp_path: Path) -> None:
    indexes_dir = tmp_path / "indexes"
    db_path = tmp_path / "storage.db"
    engine = StorageEngine(db_path=db_path)
    engine.migrate()

    provider = DeterministicFakeEmbeddingProvider(
        dimension=8,
        injected_error=ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE, "Provider down"
        ),
    )
    builder = IndexBuilder(
        indexes_dir=indexes_dir,
        provider=provider,
        repository=engine.context_indexes,
    )

    req = create_test_build_request(dimension=8)
    result, err = builder.build(req)

    # Invariant: exactly one is non-null
    assert result is None
    assert err is not None
    assert err.category == ErrorCategory.UNSUPPORTED_INPUT or err.category == ErrorCategory.TRANSIENT_SERVICE

    # Verify no orphan staging directory remains
    candidate_purpose_dir = indexes_dir / str(req.candidate_id) / req.purpose
    if candidate_purpose_dir.exists():
        staging_dirs = [d for d in candidate_purpose_dir.iterdir() if d.name.startswith("staging_")]
        assert len(staging_dirs) == 0
