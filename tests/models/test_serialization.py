"""Tests for provider serialization gate across generation and embeddings (LLM-01-S06)."""

from __future__ import annotations

import threading
import time
import uuid

from job_automation.contracts.models import ModelCall
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestSerialization:
    def test_gate_serializes_concurrent_calls(self) -> None:
        """Generation and embedding calls execute mutually exclusively through shared gate."""
        transport = ScriptedModelTransport()
        # Responses will be queued
        transport.queue_response(
            "/api/embed",
            200,
            body={"model": "minilm", "embeddings": [[0.1, 0.2]]},
            delay_seconds=0.05,
        )

        wire_gen = {
            "model": "llama3",
            "response": '{"schema_version":"1.0","assessment_id":"11111111-1111-4111-8111-111111111111","canonical_job_id":"22222222-2222-4222-8222-222222222222","posting_revision":"rev-1","profile_version":"v1","policy_version":"p1","assessment_method":"rules","rule_outcomes":[],"relevance_decision":"eligible","summary_reason":"ok","final_disposition":"eligible"}',
            "done": True,
        }
        transport.queue_response("/api/generate", 200, body=wire_gen, delay_seconds=0.05)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        in_critical_section = False
        concurrency_violation = False

        original_post = transport.post

        def tracking_post(*args: Any, **kwargs: Any) -> Any:
            nonlocal in_critical_section, concurrency_violation
            if in_critical_section:
                concurrency_violation = True
            in_critical_section = True
            try:
                time.sleep(0.02)
                return original_post(*args, **kwargs)
            finally:
                in_critical_section = False

        transport.post = tracking_post

        t1 = threading.Thread(target=lambda: provider.embed(["test"], "minilm"))
        t2 = threading.Thread(target=lambda: provider.generate(call))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not concurrency_violation
        assert not provider._gate.locked()

    def test_gate_releases_on_exception(self) -> None:
        """If an unexpected exception occurs inside harness, gate is released."""
        transport = ScriptedModelTransport()
        transport.queue_exception("/api/generate", RuntimeError("Fatal runtime failure"))

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is not None
        assert not provider._gate.locked()

