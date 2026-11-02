"""Unit tests for embedding failure modes and defensive validation."""

from __future__ import annotations

import pytest

from job_automation.context.index_embeddings import IndexEmbeddingCoordinator
from job_automation.context.index_errors import (
    IndexIncompatibleError,
    IndexValidationError,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import EmbeddingResponse, ModelProvider
from job_automation.contracts.models import ModelCall, ModelResult
from tests.context.index_test_helpers import (
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_provider_returns_error_raises_incompatible() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=8)

    provider = DeterministicFakeEmbeddingProvider(
        dimension=8,
        injected_error=ClassifiedError.from_category(
            category=ErrorCategory.TRANSIENT_SERVICE,
            message="Ollama daemon unreachable",
        ),
    )
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexIncompatibleError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "embedding failed" in exc.value.message


def test_provider_dimension_mismatch_raises_incompatible() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=8)

    # Provider returns dimension 16 instead of configured 8
    provider = DeterministicFakeEmbeddingProvider(dimension=16)
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexIncompatibleError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "dimension mismatch" in exc.value.message


def test_provider_model_identifier_mismatch_raises_incompatible() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8, model_identifier="expected-model")
    settings = create_test_index_settings(dimension=8)

    provider = DeterministicFakeEmbeddingProvider(dimension=8, model_identifier="wrong-model")
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexIncompatibleError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "Model identifier mismatch" in exc.value.message


def test_provider_model_digest_mismatch_raises_incompatible() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(
        dimension=8, model_digest="sha256_expected"
    )
    settings = create_test_index_settings(dimension=8)

    provider = DeterministicFakeEmbeddingProvider(
        dimension=8, model_digest="sha256_different"
    )
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexIncompatibleError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "Model digest mismatch" in exc.value.message


class MalformedVectorProvider(ModelProvider):
    def __init__(self, bad_vector: list) -> None:
        self.bad_vector = bad_vector

    def generate(self, call: ModelCall) -> ModelResult:
        raise NotImplementedError

    def embed(self, texts: list[str], model: str):
        return EmbeddingResponse.model_construct(
            vectors=[self.bad_vector for _ in texts],
            model_identifier="fake-embedder",
            dimension=len(self.bad_vector),
        ), None


def test_provider_returns_nan_or_inf_raises_validation() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=4)
    settings = create_test_index_settings(dimension=4)

    # Vector with float('nan')
    provider = MalformedVectorProvider([1.0, float("nan"), 0.5, 0.2])
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexValidationError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "Non-finite float" in exc.value.message


def test_provider_returns_boolean_element_raises_validation() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=4)
    settings = create_test_index_settings(dimension=4)

    # Vector with boolean True (which is an int in Python if not checked)
    provider = MalformedVectorProvider([1.0, True, 0.5, 0.2])
    coordinator = IndexEmbeddingCoordinator(provider, cfg, settings)

    with pytest.raises(IndexValidationError) as exc:
        coordinator.embed_chunks(cs.chunks)
    assert "Invalid non-float vector element" in exc.value.message
