"""Tests verifying Windows path conventions with spaces and umlauts (LLM-01-S08)."""

from __future__ import annotations

import json
from pathlib import Path
import uuid

from job_automation.configuration import AppConfig, load_config
from job_automation.contracts.models import ModelCall
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from tests.fakes.model_transport import ScriptedModelTransport

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "models"


class TestWindowsPaths:
    def test_windows_paths_with_spaces_and_umlauts(self, tmp_path: Path) -> None:
        """Provider loads and resolves correctly from Windows directory structures with spaces and umlauts."""
        windows_data_dir = (tmp_path / "Bewerbung Prüfung äöü 2026").resolve()
        cfg_file = tmp_path / "app_config_ä.json"

        cfg_content = {
            "schema_version": "1.0",
            "app_name": "JobAutomation",
            "data_root": str(windows_data_dir),
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://127.0.0.1:11434",
        }
        cfg_file.write_text(json.dumps(cfg_content), encoding="utf-8")

        config, paths = load_config(cfg_file)
        assert paths.data_root == windows_data_dir
        assert "Bewerbung Prüfung äöü 2026" in str(paths.data_root)

        transport = ScriptedModelTransport()
        with open(FIXTURES_DIR / "generation_success.json", "r", encoding="utf-8") as f:
            valid_gen = json.load(f)
        transport.queue_response("/api/generate", 200, body=valid_gen)

        resolver = InMemoryInputResolver()
        call_id = uuid.uuid4()
        bound = resolver.bind_generation(call_id, "Candidate evaluation in München")

        provider = LocalModelProvider.from_config(
            config=config,
            input_resolver=resolver,
            transport=transport,
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

