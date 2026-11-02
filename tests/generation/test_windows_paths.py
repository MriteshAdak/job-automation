"""Tests for Windows path handling: spaces, German umlauts (ä, ö, ü, ß), trailing slashes (GEN-01)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.records import FreezeManifest, StageCheckpoint, StageStatus, ProjectionIntent, ProjectionStatus
from job_automation.generation.worker import GenerationWorker
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp München",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestWindowsPaths:
    @pytest.mark.parametrize(
        "folder_name",
        [
            "data with spaces",
            "München Prüfung Köln Straße",
            "Job Automation AppData Path",
            "Kandidaten Überprüfung 2026",
        ],
    )
    def test_storage_engine_and_lock_with_special_paths(
        self, tmp_path: Path, folder_name: str
    ) -> None:
        data_root = tmp_path / folder_name
        data_root.mkdir(parents=True, exist_ok=True)

        db_path = data_root / "database" / "job_automation.db"
        raw_dir = data_root / "raw"
        artifacts_dir = data_root / "artifacts"

        engine = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=artifacts_dir)
        engine.initialize_schema()

        # Verify DB connection and table creation
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        req_id = uuid.uuid4()
        now_utc = datetime.now(timezone.utc)
        pending_req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00111111111111AAA",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=now_utc,
        )
        engine.generation_requests.create_request(pending_req)

        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00111111111111AAA",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.RUNNING,
            created_at=now_utc,
            claimed_at=now_utc,
            frozen_input_versions=FrozenInputVersions(
                posting_revision="rev-1",
                profile_version="prof-1",
                policy_version="pol-1",
                template_version="tmpl-1",
            ),
        )
        manifest = FreezeManifest(
            manifest_id=f"manifest:{req_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="prof-1",
            policy_version="pol-1",
            template_id="t1",
            template_version="tmpl-1",
            context_strategy=ContextStrategy.JSON,
            target_language="de",
            options_digest="sha256:" + "2" * 64,
            frozen_at=now_utc,
        )
        chk = StageCheckpoint(
            request_id=req_id,
            stage_name="freeze",
            stage_operation_id=f"freeze:{req_id}",
            status=StageStatus.COMPLETED,
            started_at=now_utc,
            completed_at=now_utc,
        )
        intent = ProjectionIntent(
            request_id=req_id,
            projection_revision=1,
            operation_marker=f"freeze:{req_id}",
            desired_remote_state="Running",
            payload={"Status__c": "Running"},
            status=ProjectionStatus.ACKNOWLEDGED,
            created_at=now_utc,
            updated_at=now_utc,
            acknowledged_at=now_utc,
        )
        engine.generation_work.commit_frozen_request(req, manifest, chk, intent)

        saved = engine.generation_requests.get_request(req_id)
        assert saved is not None
        assert saved.canonical_job_id == job_id

        # Test Windows lock with this path
        lock = WindowsWorkerLock(data_root)
        token = lock.acquire_lock(owner_kind=OwnerKind.GENERATION)
        assert token is not None
        token.release()

    def test_generation_worker_with_trailing_slashes_and_umlauts(self, tmp_path: Path) -> None:
        folder = tmp_path / "Bewerbungen_München"
        folder.mkdir(parents=True, exist_ok=True)
        # Trailing slash representation
        data_root_str = str(folder) + os.sep

        gateway = FakeSalesforceGatewayV2()
        worker = GenerationWorker(
            data_root=data_root_str,
            gateway=gateway,
        )
        report = worker.run_once()
        assert report.exit_code == 0
