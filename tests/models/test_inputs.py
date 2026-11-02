"""Tests for input binding, immutable resolution, and call_id validation (LLM-01-S03)."""

from __future__ import annotations

import uuid

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.models import ModelCall
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestInputs:
    def test_missing_bound_input_fails_preflight(self) -> None:
        """Call with unregistered call_id fails before transport with UNSUPPORTED_INPUT."""
        resolver = InMemoryInputResolver()
        transport = ScriptedModelTransport()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call_id = uuid.uuid4()
        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="test-model",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.UNSUPPORTED_INPUT
        assert "No immutable input bound" in result.error.message
        # Verify zero HTTP requests were made
        assert len(transport.recorded_calls) == 0

    def test_fingerprint_mismatch_fails_preflight(self) -> None:
        """Declared fingerprint mismatch with computed input fingerprint fails preflight."""
        resolver = InMemoryInputResolver()
        transport = ScriptedModelTransport()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call_id = uuid.uuid4()
        resolver.bind_generation(call_id, "actual prompt content")

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="test-model",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint="sha256:mismatchedfingerprint0000000000000000000000000000000000000000000000",
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.VALIDATION
        assert "fingerprint mismatch" in result.error.message
        assert len(transport.recorded_calls) == 0

