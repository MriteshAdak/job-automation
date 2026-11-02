"""Tests for complete audit record emission, attempt tracking, and recorder error visibility (LLM-01-S07)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

import pytest

from job_automation.contracts.models import ModelCall
from job_automation.models.audit import AuditRecordError, InMemoryAuditRecorder
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class FailingRecorder:
    def record_call(self, record: Any) -> None:
        raise OSError("Disk full: cannot write audit record")


class TestAudit:
    def test_complete_audit_record_composition(self) -> None:
        """Completed call emits LogicalCallAuditRecord with attempt records and token counts."""
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_resp = json.load(f)

        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 200, body=valid_resp)

        recorder = InMemoryAuditRecorder()
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt text", "system text")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
            audit_recorder=recorder,
        )

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v1",
            system_prompt_version="sys_v1",
            context_limit=8192,
            input_fingerprint=bound.input_fingerprint,
            requested_schema="C11_assessment",
        )

        result = provider.generate(call)
        assert result.error is None

        record = recorder.get_by_id(call_id)
        assert record is not None
        assert record.call_id == call_id
        assert record.operation_type == "relevance_assessment"
        assert record.requested_model == "llama3:8b-instruct-q4_K_M"
        assert record.observed_model == "llama3:8b-instruct-q4_K_M"
        assert record.prompt_version == "assess_v1"
        assert record.system_prompt_version == "sys_v1"
        assert record.schema_id == "C11_assessment"
        assert record.context_limit == 8192
        assert record.input_fingerprint == bound.input_fingerprint
        assert record.fingerprint_algorithm == "sha256"
        assert record.fingerprint_version == "v1"
        assert record.outcome == "success"
        assert record.attempts_count == 1
        assert len(record.attempts) == 1
        assert record.attempts[0].purpose == "initial"
        assert record.attempts[0].outcome == "success"
        assert record.token_usage is not None
        assert record.token_usage.total_tokens == 535

    def test_recorder_failure_is_visible(self) -> None:
        """A failure in the injected audit recorder raises AuditRecordError and is not swallowed."""
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_resp = json.load(f)

        transport = ScriptedModelTransport()
        transport.queue_response("/api/generate", 200, body=valid_resp)

        failing_recorder = FailingRecorder()
        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "prompt text")

        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=resolver,
            audit_recorder=failing_recorder,
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

        with pytest.raises(AuditRecordError, match="Failed to record call audit event"):
            provider.generate(call)

