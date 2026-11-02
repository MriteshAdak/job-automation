"""Unit tests for index capacity preflight and memory bounds in CONTEXT-03."""

from __future__ import annotations

import pytest

from job_automation.context.index_capacity import (
    check_index_capacity_preflight,
    estimate_matrix_bytes,
)
from job_automation.context.index_errors import IndexCapacityError
from tests.context.index_test_helpers import (
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
)


def test_estimate_matrix_bytes() -> None:
    # 10 chunks, dimension 8, 4 bytes per float32 = 320 bytes
    assert estimate_matrix_bytes(10, 8, "float32") == 320
    assert estimate_matrix_bytes(0, 8, "float32") == 0


def test_capacity_preflight_passes_for_valid_input() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=64, max_chunks=100)

    # Should not raise
    check_index_capacity_preflight(cs, cfg, settings)


def test_capacity_preflight_rejects_exceeded_chunk_count() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    # Configure limit smaller than actual chunk count
    settings = create_test_index_settings(max_chunks=len(cs.chunks) - 1)

    with pytest.raises(IndexCapacityError) as exc:
        check_index_capacity_preflight(cs, cfg, settings)
    assert "Chunk count" in exc.value.message


def test_capacity_preflight_rejects_exceeded_dimension() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=1024)
    settings = create_test_index_settings(dimension=512)

    with pytest.raises(IndexCapacityError) as exc:
        check_index_capacity_preflight(cs, cfg, settings)
    assert "Embedding dimension" in exc.value.message


def test_capacity_preflight_rejects_exceeded_chunk_text() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings()
    # Set max_text_bytes very low
    settings = settings.model_copy(update={"max_text_bytes": 10})

    with pytest.raises(IndexCapacityError) as exc:
        check_index_capacity_preflight(cs, cfg, settings)
    assert "retrieval_text" in exc.value.message


def test_capacity_preflight_rejects_exceeded_memory() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings()
    # Set memory ceiling very low
    settings = settings.model_copy(update={"max_build_memory_bytes": 10})

    with pytest.raises(IndexCapacityError) as exc:
        check_index_capacity_preflight(cs, cfg, settings)
    assert "Estimated build working memory" in exc.value.message

