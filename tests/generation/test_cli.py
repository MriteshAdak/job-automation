"""Tests for generation worker CLI subcommands: work, show, retry (GEN-01-S08)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.cli import main
from job_automation.configuration import load_config
from job_automation.contracts.enums import (
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def cli_env(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    config, paths = load_config(data_root_override=data_root)
    engine = StorageEngine.from_config(config, paths)
    engine.initialize_schema()
    return data_root, engine


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestGenerationCli:
    def test_cli_show_invalid_uuid(self, cli_env, capsys) -> None:
        data_root, _ = cli_env
        exit_code = main(["generation", "show", "--request-id", "not-a-uuid", "--data-root", str(data_root)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Invalid UUID" in captured.err

    def test_cli_show_non_existent(self, cli_env, capsys) -> None:
        data_root, _ = cli_env
        random_uuid = str(uuid.uuid4())
        exit_code = main(["generation", "show", "--request-id", random_uuid, "--data-root", str(data_root)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_cli_show_existing_text_and_json(self, cli_env, capsys) -> None:
        data_root, engine = cli_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00111111111111AAA",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(req)

        # 1. Text output
        exit_code = main(["generation", "show", "--request-id", str(req_id), "--data-root", str(data_root)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Generation Request Details" in captured.out
        assert str(req_id) in captured.out
        assert "pending" in captured.out

        # 2. JSON output
        exit_code = main(["generation", "show", "--request-id", str(req_id), "--data-root", str(data_root), "--json"])
        assert exit_code == 0
        captured_json = capsys.readouterr()
        data = json.loads(captured_json.out)
        assert data["request"]["request_id"] == str(req_id)
        assert data["request"]["state"] == "pending"

    def test_cli_retry_non_failed_fails(self, cli_env, capsys) -> None:
        data_root, engine = cli_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(req)

        exit_code = main(["generation", "retry", "--request-id", str(req_id), "--data-root", str(data_root)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Only failed requests can be retried" in captured.err

    def test_cli_retry_failed_resets_state(self, cli_env, capsys) -> None:
        data_root, engine = cli_env
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        req = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.FAILED,
            created_at=now_utc,
            completed_at=now_utc,
            error=ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="Test failure",
            ),
        )
        engine.generation_requests.create_request(req)

        exit_code = main(["generation", "retry", "--request-id", str(req_id), "--data-root", str(data_root)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "reset to state 'pending' for retry" in captured.out

        # Verify state in DB
        updated = engine.generation_requests.get_request(req_id)
        assert updated is not None
        assert updated.state == GenerationProcessing.PENDING
        assert updated.error is None
        assert updated.completed_at is None
