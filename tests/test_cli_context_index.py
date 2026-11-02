"""Integration tests for CLI context index subcommands."""

from __future__ import annotations

import json
from pathlib import Path

from job_automation.cli import main
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine
from tests.context.index_test_helpers import create_test_profile_snapshot


def test_cli_context_index_workflow(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    config_path = tmp_path / "app.json"

    cfg_data = {
        "schema_version": "1.0",
        "app_name": "JobAutomation",
        "data_root": str(data_root),
        "display_timezone": "Europe/Berlin",
        "model_service_url": "http://127.0.0.1:11434",
    }
    config_path.write_text(json.dumps(cfg_data), encoding="utf-8")

    # Initialize storage and save an approved candidate snapshot
    engine = StorageEngine(
        db_path=data_root / "database" / "job_automation.db",
        profiles_dir=data_root / "profiles",
    )
    engine.migrate()

    snap = create_test_profile_snapshot(profile_version="v1")
    cand_id = str(snap.candidate_id)

    engine.profiles.publish_snapshot(
        snapshot=snap,
        version_sequence=1,
        predecessor_version=None,
        content_hash="sha256:testhash",
        approved_by=snap.approval_metadata.approved_by,
        approved_at=snap.approval_metadata.approved_at,
    )
    engine.close()

    # Synthetic model config path
    model_cfg_path = tmp_path / "model_cfg.json"
    model_cfg_data = {
        "schema_version": "1.0",
        "configuration_version": "v1",
        "model_identifier": "fake-embedder",
        "dimension": 8,
        "verification_provenance": "synthetic_fake",
        "runtime_version": "1.0",
        "provider_version": "1.0",
    }
    model_cfg_path.write_text(json.dumps(model_cfg_data), encoding="utf-8")

    # 1. Mock LocalModelProvider with DeterministicFakeEmbeddingProvider
    from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider

    monkeypatch.setattr(
        "job_automation.models.provider.LocalModelProvider.from_config",
        lambda *args, **kwargs: DeterministicFakeEmbeddingProvider(dimension=8),
    )

    # 2. Build and auto-activate index
    exit_code = main(
        [
            "context",
            "index",
            "build",
            "--candidate-id",
            cand_id,
            "--purpose",
            "assessment",
            "--config",
            str(config_path),
            "--model-config",
            str(model_cfg_path),
            "--activate",
        ]
    )
    assert exit_code == 0

    # 3. Status check
    exit_code = main(
        [
            "context",
            "index",
            "status",
            "--candidate-id",
            cand_id,
            "--purpose",
            "assessment",
            "--config",
            str(config_path),
        ]
    )
    assert exit_code == 0

    # 4. Verify check
    exit_code = main(
        [
            "context",
            "index",
            "verify",
            "--candidate-id",
            cand_id,
            "--purpose",
            "assessment",
            "--config",
            str(config_path),
        ]
    )
    assert exit_code == 0

    # 5. Cleanup check
    exit_code = main(
        [
            "context",
            "index",
            "cleanup",
            "--candidate-id",
            cand_id,
            "--purpose",
            "assessment",
            "--config",
            str(config_path),
        ]
    )
    assert exit_code == 0
