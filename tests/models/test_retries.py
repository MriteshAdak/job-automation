"""Tests for bounded retries, backoff calculations, and attempt bounding (LLM-01-S06)."""

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


class TestRetries:
    def test_transient_error_recovered_on_second_attempt(self) -> None:
        """Transient 503 service error followed by valid response succeeds within retry cap."""
        clock = ScriptedClock()
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        # 1st attempt: 503 transient service error
        transport.queue_response("/api/generate", 503, body=b'{"error": "busy"}')

        # 2nd attempt: valid response
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_resp = json.load(f)
        transport.queue_response("/api/generate", 200, body=valid_resp)

        settings = ModelProviderSettings(
            max_transport_attempts=3,
            initial_backoff_seconds=1.0,
        )

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt content")

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
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is None
        assert result.parsed_output is not None
        assert len(transport.recorded_calls) == 2
        assert sleeper.total_slept >= 1.0

    def test_exhaustion_of_retries_returns_final_error(self) -> None:
        """When transport attempts reach max_transport_attempts, final error is returned."""
        clock = ScriptedClock()
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        # Queue 3 transient 502 errors
        transport.queue_response("/api/generate", 502, body=b'{"error": "bad gateway 1"}')
        transport.queue_response("/api/generate", 502, body=b'{"error": "bad gateway 2"}')
        transport.queue_response("/api/generate", 502, body=b'{"error": "bad gateway 3"}')

        settings = ModelProviderSettings(max_transport_attempts=3)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt content")

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
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.TRANSIENT_SERVICE
        assert len(transport.recorded_calls) == 3

    def test_non_recoverable_error_does_not_retry(self) -> None:
        """Permanent 401 or 403 error does not loop and aborts after 1 attempt."""
        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 401, body=b'{"error": "unauthorized"}')

        settings = ModelProviderSettings(max_transport_attempts=5)
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
            model_identifier="test-model",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.AUTHENTICATION
        assert len(transport.recorded_calls) == 1

