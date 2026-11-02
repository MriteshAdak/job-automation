"""Tests for structured generation execution and wire envelope parsing (LLM-01-S04)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

import pytest

from job_automation.contracts.enums import AssessmentDisposition
from job_automation.contracts.models import ModelCall
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestGeneration:
    def test_successful_structured_generation(self) -> None:
        """Generation receives valid response envelope and parses C11 Assessment."""
        fixture_path = FIXTURES_DIR / "generation_success.json"
        with open(fixture_path, "r", encoding="utf-8") as f:
            wire_response = json.load(f)

        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 200, body=wire_response)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(
            call_id,
            prompt="Job posting text and candidate profile",
            system_prompt="Evaluate fit",
        )

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v1",
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is None
        assert result.parsed_output is not None
        assert result.parsed_output["relevance_decision"] == "eligible"
        assert result.parsed_output["relevance_score"] == 92.0
        assert result.token_usage is not None
        assert result.token_usage.prompt_tokens == 450
        assert result.token_usage.completion_tokens == 85
        assert result.token_usage.total_tokens == 535
        assert result.latency_ms >= 0.0

        # Verify wire call payload
        assert len(transport.recorded_calls) == 1
        sent = transport.recorded_calls[0]
        assert sent["path"] == "/api/generate"
        assert sent["payload"]["model"] == "llama3:8b-instruct-q4_K_M"
        assert sent["payload"]["prompt"] == "Job posting text and candidate profile"
        assert sent["payload"]["system"] == "Evaluate fit"
        assert sent["payload"]["stream"] is False
        assert "format" in sent["payload"]

