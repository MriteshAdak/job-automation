"""Tests for malformed output handling and bounded regeneration control (LLM-01-S06)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.models import ModelCall
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import (
    ScriptedClock,
    ScriptedModelTransport,
    ScriptedSleeper,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestMalformedOutput:
    def test_default_policy_zero_regeneration_fails_immediately(self) -> None:
        """By default (max_malformed_regenerations=0), malformed output fails immediately on attempt 1."""
        transport = ScriptedModelTransport()
        with open(FIXTURES_DIR / "generation_malformed.json", "r", encoding="utf-8") as f:
            malformed_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=malformed_resp)

        # Default max_malformed_regenerations is 0
        settings = ModelProviderSettings(max_malformed_regenerations=0, max_transport_attempts=3)
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt")

        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.MODEL_OUTPUT
        assert len(transport.recorded_calls) == 1

    def test_single_regeneration_success_when_enabled(self) -> None:
        """When max_malformed_regenerations=1, malformed output on attempt 1 is regenerated and succeeds on attempt 2."""
        clock = ScriptedClock()
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        # 1st attempt: malformed markdown fences
        with open(FIXTURES_DIR / "generation_malformed.json", "r", encoding="utf-8") as f:
            malformed_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=malformed_resp)

        # 2nd attempt: valid C11 output
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=valid_resp)

        settings = ModelProviderSettings(
            max_malformed_regenerations=1,
            max_transport_attempts=3,
        )
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt")

        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=resolver,
            clock=clock,
            sleeper=sleeper,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is None
        assert result.parsed_output is not None
        assert len(transport.recorded_calls) == 2

    def test_two_consecutive_malformed_outputs_exhaust_regeneration_allowance(self) -> None:
        """When attempt 1 and 2 are both malformed, call aborts after 2 attempts with MODEL_OUTPUT."""
        clock = ScriptedClock()
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        with open(FIXTURES_DIR / "generation_malformed.json", "r", encoding="utf-8") as f:
            malformed_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=malformed_resp)
        transport.queue_response("/api/generate", 200, body=malformed_resp)

        settings = ModelProviderSettings(
            max_malformed_regenerations=1,
            max_transport_attempts=5,  # Higher attempt cap, but regeneration cap is 1
        )
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt")

        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=resolver,
            clock=clock,
            sleeper=sleeper,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.MODEL_OUTPUT
        assert len(transport.recorded_calls) == 2

