"""Unit tests for IndexEmbeddingCoordinator and ModelProvider integration."""

from __future__ import annotations

import math
import pytest

from job_automation.context.index_embeddings import IndexEmbeddingCoordinator
from job_automation.context.index_errors import (
    IndexCapacityError,
    IndexValidationError,
)
from job_automation.context.index_model_audit import IndexAuditSink
from tests.context.index_test_helpers import (
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_embed_chunks_normal_execution() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=8)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    audit = IndexAuditSink()

    coordinator = IndexEmbeddingCoordinator(
        provider=provider, config=cfg, settings=settings, audit_sink=audit
    )

    vectors, call_ids, total_bytes = coordinator.embed_chunks(cs.chunks)

    assert len(vectors) == len(cs.chunks)
    assert len(call_ids) == 1
    assert total_bytes > 0

    for vec in vectors:
        assert len(vec) == 8
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 1e-4


def test_embed_empty_chunks_returns_immediately() -> None:
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=8)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    coordinator = IndexEmbeddingCoordinator(
        provider=provider, config=cfg, settings=settings
    )

    vectors, call_ids, total_bytes = coordinator.embed_chunks([])
    assert vectors == []
    assert call_ids == []
    assert total_bytes == 0
    assert len(provider.calls) == 0


def test_document_prefix_applied() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8).model_copy(
        update={"document_prefix": "doc: "}
    )
    settings = create_test_index_settings(dimension=8)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    coordinator = IndexEmbeddingCoordinator(
        provider=provider, config=cfg, settings=settings
    )
    coordinator.embed_chunks(cs.chunks)

    assert len(provider.calls) == 1
    for text in provider.calls[0]:
        assert text.startswith("doc: ")


def test_batching_by_count() -> None:
    cs = create_test_chunk_set()
    # Batch size of 1 item per call
    cfg = create_test_embedding_config(dimension=8).model_copy(
        update={"max_batch_items": 1}
    )
    settings = create_test_index_settings(dimension=8)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    coordinator = IndexEmbeddingCoordinator(
        provider=provider, config=cfg, settings=settings
    )
    vectors, call_ids, _ = coordinator.embed_chunks(cs.chunks)

    assert len(provider.calls) == len(cs.chunks)
    assert len(call_ids) == len(cs.chunks)
    assert len(vectors) == len(cs.chunks)

