"""Tests for contract boundaries, protocol conformance, and record invariants (LLM-01-S01)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import EmbeddingResponse, ModelProvider
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.models.records import (
    AttemptAuditRecord,
    BoundEmbeddingInput,
    BoundGenerationInput,
    LogicalCallAuditRecord,
)
from tests.fakes.model_transport import ScriptedModelTransport


class TestContractBoundary:
    def test_provider_protocol_conformance(self) -> None:
        """LocalModelProvider satisfies runtime_checkable ModelProvider protocol."""
        resolver = InMemoryInputResolver()
        transport = ScriptedModelTransport()
        from job_automation.models.configuration import ModelProviderSettings

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )
        assert isinstance(provider, ModelProvider)

    def test_model_result_exclusive_success_or_error(self) -> None:
        """ModelResult cannot simultaneously contain an error and parsed/text output."""
        call_id = uuid.uuid4()
        err = ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE,
            "Service unavailable",
        )

        # Ambiguous output + error must fail validation
        with pytest.raises(ValidationError, match="ModelResult with error must have null output_text and parsed_output"):
            ModelResult(
                call_id=call_id,
                model_identifier="test-model",
                output_text='{"disposition": "eligible"}',
                error=err,
                latency_ms=100.0,
            )

        with pytest.raises(ValidationError, match="ModelResult with error must have null output_text and parsed_output"):
            ModelResult(
                call_id=call_id,
                model_identifier="test-model",
                parsed_output={"disposition": "eligible"},
                error=err,
                latency_ms=100.0,
            )

        # Valid success
        success_res = ModelResult(
            call_id=call_id,
            model_identifier="test-model",
            output_text='{"disposition": "eligible"}',
            parsed_output={"disposition": "eligible"},
            error=None,
            latency_ms=100.0,
        )
        assert success_res.error is None
        assert success_res.parsed_output is not None

        # Valid error
        error_res = ModelResult(
            call_id=call_id,
            model_identifier="test-model",
            output_text=None,
            parsed_output=None,
            error=err,
            latency_ms=50.0,
        )
        assert error_res.error is not None
        assert error_res.output_text is None
        assert error_res.parsed_output is None

    def test_embedding_response_metadata_extension(self) -> None:
        """EmbeddingResponse supports optional call_id, model_digest, and token_usage with backwards compatibility."""
        call_id = uuid.uuid4()
        # Minimal legacy creation
        legacy_resp = EmbeddingResponse(
            vectors=[[0.1, 0.2]],
            model_identifier="minilm",
            dimension=2,
        )
        assert legacy_resp.call_id is None
        assert legacy_resp.model_digest is None
        assert legacy_resp.token_usage is None

        # Extended creation
        ext_resp = EmbeddingResponse(
            vectors=[[0.1, 0.2]],
            model_identifier="minilm",
            dimension=2,
            call_id=call_id,
            model_digest="sha256:abc",
            token_usage=TokenUsage(total_tokens=10),
        )
        assert ext_resp.call_id == call_id
        assert ext_resp.model_digest == "sha256:abc"
        assert ext_resp.token_usage.total_tokens == 10

    def test_bound_input_mutation_resilience(self) -> None:
        """Mutating caller dictionary after binding does not alter bound input."""
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        meta = {"tag": "initial"}
        bound = resolver.bind_generation(call_id, "prompt text", "system text", metadata=meta)

        # Mutate caller dictionary
        meta["tag"] = "mutated"
        meta["extra"] = "injected"

        resolved = resolver.resolve_generation_input(call_id)
        assert resolved is not None
        assert resolved.metadata.get("tag") == "initial"
        assert "extra" not in resolved.metadata

