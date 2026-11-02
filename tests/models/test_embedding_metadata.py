"""Tests for embedding audit metadata, call_id correlation, and provenance (LLM-01-S05)."""

from __future__ import annotations

import uuid

from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport


class TestEmbeddingMetadata:
    def test_embedding_success_audit_correlation(self) -> None:
        """EmbeddingResponse provides call_id to inspect corresponding LogicalCallAuditRecord."""
        transport = ScriptedModelTransport()
        transport.queue_response(
            "/api/embed",
            200,
            body={"model": "minilm", "embeddings": [[0.1, 0.2]], "prompt_eval_count": 10},
        )

        recorder = InMemoryAuditRecorder()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
            audit_recorder=recorder,
        )

        resp, err = provider.embed(["test text"], "minilm")
        assert err is None
        assert resp is not None
        assert resp.call_id is not None

        # Verify audit record matches call_id
        record = recorder.get_by_id(resp.call_id)
        assert record is not None
        assert record.operation_type == "embedding"
        assert record.requested_model == "minilm"
        assert record.observed_model == "minilm"
        assert record.outcome == "success"
        assert record.token_usage is not None
        assert record.token_usage.total_tokens == 10
        assert len(record.attempts) == 1

    def test_embedding_failure_audit_correlation(self) -> None:
        """Embedding failure provides call_id in ClassifiedError.details linking to audit record."""
        transport = ScriptedModelTransport()
        transport.queue_response("/api/embed", 500, body=b'{"error": "runtime crashed"}')

        recorder = InMemoryAuditRecorder()
        provider = LocalModelProvider(
            settings=ModelProviderSettings(max_transport_attempts=1),
            transport=transport,
            input_resolver=InMemoryInputResolver(),
            audit_recorder=recorder,
        )

        resp, err = provider.embed(["test text"], "minilm")
        assert resp is None
        assert err is not None
        assert err.details is not None
        assert "call_id" in err.details

        failed_call_id = uuid.UUID(err.details["call_id"])
        record = recorder.get_by_id(failed_call_id)
        assert record is not None
        assert record.operation_type == "embedding"
        assert record.outcome == "transient_service"

