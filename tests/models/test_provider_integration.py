"""End-to-end integration tests for LocalModelProvider with AppConfig and fake transport (LLM-01-S08)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from job_automation.configuration import AppConfig
from job_automation.contracts.models import ModelCall
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestProviderIntegration:
    def test_provider_from_config_complete_flow(self, tmp_path: Path) -> None:
        """Provider constructed from AppConfig executes generation and embedding with audit recording."""
        data_dir = (tmp_path / "Data Prüfung ä").resolve()
        cfg = AppConfig(
            data_root=str(data_dir),
            model_service_url="http://127.0.0.1:11434",
        )

        transport = ScriptedModelTransport()
        recorder = InMemoryAuditRecorder()
        resolver = InMemoryInputResolver()

        provider = LocalModelProvider.from_config(
            config=cfg,
            input_resolver=resolver,
            audit_recorder=recorder,
            transport=transport,
        )

        # 1. Generation call
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_gen = json.load(f)
        transport.queue_response("/api/generate", 200, body=valid_gen)

        call_id = uuid.uuid4()
        bound_gen = resolver.bind_generation(call_id, "Assess candidate", "System prompt")

        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
            context_limit=4096,
            input_fingerprint=bound_gen.input_fingerprint,
            requested_schema="C11_assessment",
        )

        gen_result = provider.generate(call)
        assert gen_result.error is None
        assert gen_result.parsed_output is not None
        assert gen_result.parsed_output["relevance_decision"] == "eligible"

        # 2. Embedding call
        wire_embed = {
            "model": "all-minilm",
            "embeddings": [[0.1, 0.2, 0.3]],
            "prompt_eval_count": 5,
        }
        transport.queue_response("/api/embed", 200, body=wire_embed)

        embed_resp, embed_err = provider.embed(["search query"], "all-minilm")
        assert embed_err is None
        assert embed_resp is not None
        assert len(embed_resp.vectors) == 1

        # 3. Verify audit records
        assert len(recorder.records) == 2
        gen_record = recorder.get_by_id(call_id)
        embed_record = recorder.get_by_id(embed_resp.call_id)
        assert gen_record is not None
        assert embed_record is not None
        assert gen_record.operation_type == "relevance_assessment"
        assert embed_record.operation_type == "embedding"

