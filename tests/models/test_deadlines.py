"""Tests for deadline enforcement, timeout bounding, and queue wait accounting (LLM-01-S02, S06)."""

from __future__ import annotations

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


class TestDeadlines:
    def test_deadline_exhaustion_during_retries(self) -> None:
        """Call aborts when cumulative retry duration and backoff exceeds total_deadline_seconds."""
        clock = ScriptedClock(initial_monotonic=100.0)
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        # Queue transient errors that will trigger retries
        transport.queue_response("/api/generate", 503, body=b'{"error": "busy"}', delay_seconds=20.0)
        transport.queue_response("/api/generate", 503, body=b'{"error": "busy"}', delay_seconds=20.0)

        settings = ModelProviderSettings(
            total_deadline_seconds=30.0,  # Short deadline
            read_timeout_seconds=25.0,
            initial_backoff_seconds=2.0,
            max_transport_attempts=5,
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
            model_identifier="test-model",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert result.error.category == ErrorCategory.TRANSIENT_SERVICE
        # Did not loop all 5 times because deadline was exhausted
        assert len(transport.recorded_calls) < 5
        assert result.latency_ms >= 20000.0

    def test_lock_timeout_returns_transient_service_error(self) -> None:
        """If provider gate is locked longer than deadline, call returns ClassifiedError."""
        clock = ScriptedClock(initial_monotonic=100.0)
        sleeper = ScriptedSleeper(clock)
        transport = ScriptedModelTransport(clock)

        settings = ModelProviderSettings(total_deadline_seconds=0.01)
        resolver = InMemoryInputResolver()
        provider = LocalModelProvider(
            settings=settings,
            transport=transport,
            input_resolver=resolver,
            clock=clock,
            sleeper=sleeper,
        )

        # Acquire gate externally to simulate concurrent caller holding lock
        assert provider._gate.acquire()
        try:
            call_id = uuid.uuid4()
            bound = resolver.bind_generation(call_id, "prompt")
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
            assert result.error.category == ErrorCategory.TRANSIENT_SERVICE
            assert "inference gate" in result.error.message
        finally:
            provider._gate.release()

