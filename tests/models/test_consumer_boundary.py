"""Tests proving model errors never become silent job rejections at consumer boundary (LLM-01-S08)."""

from __future__ import annotations

import uuid

from job_automation.contracts.enums import AssessmentDisposition
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class MockRelevanceAssessor:
    """Downstream consumer combining hard criteria with LLM generation."""

    def __init__(self, provider: LocalModelProvider) -> None:
        self.provider = provider

    def assess_job(self, call: ModelCall) -> tuple[str, str]:
        """Assess a job posting using ModelProvider.

        Returns (disposition, explanation).
        Crucial requirement: Model errors must NEVER turn into job rejection.
        """
        result = self.provider.generate(call)
        if result.error is not None:
            # Model service failure, context overflow, or invalid output:
            # Must remain reviewable/pending, never rejected!
            return "review", f"Model assessment deferred due to error: {result.error.category} ({result.error.message})"

        assert result.parsed_output is not None
        decision = result.parsed_output.get("final_disposition", "review")
        return decision, result.parsed_output.get("summary_reason", "Assessed by model")


class TestConsumerBoundary:
    def test_transient_service_error_does_not_reject_job(self) -> None:
        """Transport service failure leaves job in review/pending, never rejected."""
        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 503, body=b'{"error": "server busy"}')

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "Job posting requirements")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        assessor = MockRelevanceAssessor(provider)
        disposition, explanation = assessor.assess_job(call)

        assert disposition != "rejected"
        assert disposition == "review"
        assert "transient_service" in explanation

    def test_context_budget_overflow_does_not_reject_job(self) -> None:
        """Context overflow leaves job in review/pending, never rejected."""
        transport = ScriptedModelTransport()
        transport.queue_response(
            "/api/generate",
            400,
            body=b'{"error": "prompt exceeds context length of 2048 tokens"}',
        )

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "Very long job description")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b",
            prompt_version="v1",
            context_limit=2048,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        assessor = MockRelevanceAssessor(provider)
        disposition, explanation = assessor.assess_job(call)

        assert disposition != "rejected"
        assert disposition == "review"
        assert "context_budget" in explanation

    def test_malformed_output_does_not_reject_job(self) -> None:
        """Malformed model response leaves job in review/pending, never rejected."""
        transport = ScriptedModelTransport()
        transport.queue_response(
            "/api/generate",
            200,
            body={"model": "llama3:8b", "response": "Garbage text", "done": True},
        )

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "Job description")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1, max_malformed_regenerations=0),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        assessor = MockRelevanceAssessor(provider)
        disposition, explanation = assessor.assess_job(call)

        assert disposition != "rejected"
        assert disposition == "review"
        assert "model_output" in explanation

