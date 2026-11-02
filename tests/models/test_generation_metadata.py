"""Tests for generation metadata mapping, token usage nullability, and digest verification (LLM-01-S04)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.models import ModelCall
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestGenerationMetadata:
    def test_absent_token_usage_retains_null_not_zero(self) -> None:
        """When model runtime does not report token counts, token_usage is None."""
        fixture_path = FIXTURES_DIR / "generation_success.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            wire_response = json.load(f)

        # Remove token usage metrics from wire response
        wire_response.pop("prompt_eval_count", None)
        wire_response.pop("eval_count", None)

        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 200, body=wire_response)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt content")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is None
        assert result.token_usage is None

    def test_pinned_model_digest_mismatch_fails_call(self) -> None:
        """Call pinning expected model_digest fails if runtime returns a different digest."""
        fixture_path = FIXTURES_DIR / "generation_success.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            wire_response = json.load(f)

        wire_response["digest"] = "sha256:differentdigest123"

        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 200, body=wire_response)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt content")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            model_digest="sha256:expecteddigest456",  # Pinned digest mismatch
            prompt_version="v1",
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.MODEL_OUTPUT
        assert "digest" in result.error.message

