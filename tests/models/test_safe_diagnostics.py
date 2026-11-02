"""Tests for privacy boundaries, credential redaction, and log sanitization (LLM-01-S07)."""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.diagnostics import (
    redact_url_credentials,
    safe_result_summary,
    sanitize_log_text,
)
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestSafeDiagnostics:
    def test_sentinel_prompt_never_leaks_to_audit_or_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Private sentinel strings in prompts or input texts never appear in audit records or error details."""
        sentinel_secret = "TOP_SECRET_CANDIDATE_DATA_XYZ_999"
        transport = ScriptedModelTransport()
        # Fail with a transport error
        transport.queue_response("/api/generate", 500, body=b'{"error": "runtime crash"}')

        recorder = InMemoryAuditRecorder()
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(
            call_id,
            prompt=f"Candidate resume text with {sentinel_secret}",
            system_prompt="Assess strictly",
        )

        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1),
            transport=transport,
            input_resolver=resolver,
            audit_recorder=recorder,
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

        with caplog.at_level(logging.DEBUG):
            result = provider.generate(call)

        # 1. Error message and details must not contain sentinel
        assert result.error is not None
        assert sentinel_secret not in result.error.message
        assert sentinel_secret not in json.dumps(result.error.details or {})

        # 2. Audit record must not contain sentinel
        record = recorder.get_by_id(call_id)
        assert record is not None
        serialized_audit = record.model_dump_json()
        assert sentinel_secret not in serialized_audit

        # 3. Captured logs must not contain sentinel
        assert sentinel_secret not in caplog.text

    def test_url_credentials_redacted(self) -> None:
        raw_url = "http://admin:super_secret_password@127.0.0.1:11434/api"
        redacted = redact_url_credentials(raw_url)
        assert "super_secret_password" not in redacted
        assert "admin" not in redacted
        assert "://[REDACTED]@" in redacted

    def test_log_text_sanitization(self) -> None:
        raw = "Line 1\nLine 2\r\n\x00ControlChar\tTab"
        sanitized = sanitize_log_text(raw)
        assert "\n" not in sanitized
        assert "\r" not in sanitized
        assert "\x00" not in sanitized
        assert "Line 1 Line 2 ControlChar Tab" in sanitized

    def test_safe_result_summary_projection(self) -> None:
        call_id = uuid.uuid4()
        result = ModelResult(
            call_id=call_id,
            model_identifier="llama3",
            output_text='{"private": "data"}',
            parsed_output={"private": "data"},
            latency_ms=120.0,
        )
        summary = safe_result_summary(result)
        serialized = json.dumps(summary)
        # Summary must NOT contain output_text or parsed_output
        assert "private" not in serialized
        assert summary["call_id"] == str(call_id)
        assert summary["model_identifier"] == "llama3"

