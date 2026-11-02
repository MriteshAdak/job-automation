"""Tests for query embedding coordination and validation (S03, RET-12)."""

from __future__ import annotations

import math
import uuid
import pytest

from job_automation.context.errors import (
    RetrievalChannelError,
    RetrievalIncompatibleError,
)
from job_automation.context.queries import DefaultQueryBuilder
from job_automation.context.query_embeddings import QueryEmbeddingCoordinator
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import EmbeddingResponse
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage
from tests.context.index_test_helpers import create_test_embedding_config
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_query_embeddings_success_and_normalization() -> None:
    provider = DeterministicFakeEmbeddingProvider(dimension=8, model_digest="digest-123")
    emb_config = create_test_embedding_config(
        dimension=8,
        model_identifier="fake-embedder",
        model_digest="digest-123",
    )
    # Add prefix to test query_prefix application
    emb_config = emb_config.model_copy(update={"query_prefix": "search_query: "})

    builder = DefaultQueryBuilder()
    qset = builder.build_queries(["C++ distributed systems", "Python data engineering"])

    coordinator = QueryEmbeddingCoordinator(provider)
    vectors, call_ids = coordinator.embed_queries(qset, emb_config, normalize=True)

    assert len(vectors) == 2
    assert "q_0" in vectors
    assert "q_1" in vectors
    assert len(call_ids) == 1

    # Verify query_prefix was applied
    assert provider.calls[0][0].startswith("search_query: ")
    assert provider.calls[0][1].startswith("search_query: ")

    # Verify unit L2 normalization
    for vec in vectors.values():
        assert len(vec) == 8
        norm = math.sqrt(sum(v * v for v in vec))
        assert math.isclose(norm, 1.0, rel_tol=1e-5)


def test_query_embeddings_dimension_mismatch_fails() -> None:
    provider = DeterministicFakeEmbeddingProvider(dimension=16)  # Provider returns 16
    emb_config = create_test_embedding_config(dimension=8)       # Expected is 8

    builder = DefaultQueryBuilder()
    qset = builder.build_queries(["Machine Learning Engineer"])

    coordinator = QueryEmbeddingCoordinator(provider)
    with pytest.raises(RetrievalIncompatibleError, match="dimension 16 does not match expected 8"):
        coordinator.embed_queries(qset, emb_config)


def test_query_embeddings_digest_mismatch_fails() -> None:
    provider = DeterministicFakeEmbeddingProvider(dimension=8, model_digest="new-digest-456")
    emb_config = create_test_embedding_config(dimension=8, model_digest="expected-digest-123")

    builder = DefaultQueryBuilder()
    qset = builder.build_queries(["Backend Developer"])

    coordinator = QueryEmbeddingCoordinator(provider)
    with pytest.raises(RetrievalIncompatibleError, match="model digest 'new-digest-456' does not match"):
        coordinator.embed_queries(qset, emb_config)


def test_query_embeddings_provider_failure_surfaces() -> None:
    injected_err = ClassifiedError.from_category(
        ErrorCategory.TRANSIENT_SERVICE,
        "Embedding service timeout",
    )
    provider = DeterministicFakeEmbeddingProvider(dimension=8, injected_error=injected_err)
    emb_config = create_test_embedding_config(dimension=8)

    builder = DefaultQueryBuilder()
    qset = builder.build_queries(["DevOps Specialist"])

    coordinator = QueryEmbeddingCoordinator(provider)
    with pytest.raises(RetrievalChannelError, match="Query embedding generation failed: Embedding service timeout"):
        coordinator.embed_queries(qset, emb_config)

