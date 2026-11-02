"""Tests for validated vector embeddings and dimension consistency (LLM-01-S05)."""

from __future__ import annotations

import math

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.models.configuration import (
    ModelCapabilities,
    ModelProviderSettings,
)
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestEmbeddings:
    def test_three_texts_produce_three_ordered_vectors(self) -> None:
        """Acceptance criteria: Three texts produce three correctly ordered vectors for the selected model."""
        transport = ScriptedModelTransport()
        wire_resp = {
            "model": "all-minilm",
            "embeddings": [
                [0.1, 0.2, 0.3],
                [0.4, 0.5, 0.6],
                [0.7, 0.8, 0.9],
            ],
            "prompt_eval_count": 42,
        }
        transport.queue_response("/api/embed", 200, body=wire_resp)

        settings = ModelProviderSettings(
            models={
                "all-minilm": ModelCapabilities(
                    model_identifier="all-minilm",
                    max_context_tokens=512,
                    dimension=3,
                )
            }
        )

        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        texts = ["Skill: Python", "Role: Engineer", "Location: Berlin"]
        resp, err = provider.embed(texts, "all-minilm")

        assert err is None
        assert resp is not None
        assert len(resp.vectors) == 3
        assert resp.vectors[0] == [0.1, 0.2, 0.3]
        assert resp.vectors[1] == [0.4, 0.5, 0.6]
        assert resp.vectors[2] == [0.7, 0.8, 0.9]
        assert resp.dimension == 3
        assert resp.model_identifier == "all-minilm"
        assert resp.call_id is not None
        assert resp.token_usage is not None
        assert resp.token_usage.total_tokens == 42

    def test_vector_count_mismatch_fails_with_model_output(self) -> None:
        """Runtime returning fewer or more vectors than input texts fails entire batch with MODEL_OUTPUT."""
        transport = ScriptedModelTransport()
        # Input has 2 texts, but runtime returns 1 vector
        wire_resp = {
            "model": "all-minilm",
            "embeddings": [[0.1, 0.2]],
        }
        transport.queue_response("/api/embed", 200, body=wire_resp)

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        resp, err = provider.embed(["text 1", "text 2"], "all-minilm")
        assert resp is None
        assert err is not None
        assert err.category == ErrorCategory.MODEL_OUTPUT
        assert "count mismatch" in err.message

    def test_mixed_vector_dimensions_fails_with_model_output(self) -> None:
        """Inconsistent vector dimensions across batch elements fails with MODEL_OUTPUT."""
        transport = ScriptedModelTransport()
        wire_resp = {
            "model": "all-minilm",
            "embeddings": [
                [0.1, 0.2, 0.3],
                [0.4, 0.5],  # Dimension mismatch (2 vs 3)
            ],
        }
        transport.queue_response("/api/embed", 200, body=wire_resp)

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        resp, err = provider.embed(["text 1", "text 2"], "all-minilm")
        assert resp is None
        assert err is not None
        assert err.category == ErrorCategory.MODEL_OUTPUT
        assert "dimensions" in err.message

    def test_non_finite_or_boolean_elements_rejected(self) -> None:
        """Vectors containing boolean or non-finite elements fail validation."""
        transport = ScriptedModelTransport()
        wire_resp = {
            "model": "all-minilm",
            "embeddings": [
                [0.1, True, 0.3],  # True is boolean, forbidden
            ],
        }
        transport.queue_response("/api/embed", 200, body=wire_resp)

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        resp, err = provider.embed(["text 1"], "all-minilm")
        assert resp is None
        assert err is not None
        assert err.category == ErrorCategory.MODEL_OUTPUT
        assert "non-finite or non-numeric" in err.message

    def test_empty_batch_rejected(self) -> None:
        """Empty input batch is rejected at preflight without transport."""
        transport = ScriptedModelTransport()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        resp, err = provider.embed([], "all-minilm")
        assert resp is None
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert len(transport.recorded_calls) == 0

    def test_empty_individual_text_rejected(self) -> None:
        """Individual whitespace-only text is rejected at preflight without transport."""
        transport = ScriptedModelTransport()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
        )

        resp, err = provider.embed(["valid", "   "], "all-minilm")
        assert resp is None
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "empty or whitespace-only" in err.message
        assert len(transport.recorded_calls) == 0
