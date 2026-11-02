"""Tests for generation worker lifecycle, lock acquisition, bounded cycles, and reporting (GEN-01-S03/S08)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.configuration import AppConfig, ResolvedPaths
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.records import (
    FreezeManifest,
    GenerationWorkerReport,
)
from job_automation.generation.reporting import format_worker_report
from job_automation.generation.settings import GenerationSettings
from job_automation.generation.worker import GenerationWorker
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine
from tests.fakes.fake_services import FakeGenerator, FakeRendererDelivery
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.generation.test_coordinator import FakeInputService, FakeValidator


@pytest.fixture
def test_env(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(
        db_path=data_root / "jobs.db",
        raw_dir=data_root / "raw",
        artifacts_dir=data_root / "artifacts",
    )
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


class TestGenerationWorker:
    def test_worker_run_once_no_work_returns_exit_code_0(self, test_env) -> None:
        data_root, engine = test_env
        gateway = FakeSalesforceGatewayV2()
        worker = GenerationWorker(
            data_root=data_root,
            gateway=gateway,
            engine=engine,
        )

        report = worker.run_once()
        assert report.exit_code == 0
        assert report.scanned_requests == 0
        assert report.completed_requests == 0
        assert report.blocked_requests == 0
        assert report.failed_requests == 0

    def test_worker_run_once_blocked_when_missing_generator_returns_exit_code_4(
        self, test_env
    ) -> None:
        data_root, engine = test_env
        gateway = FakeSalesforceGatewayV2()

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {
                "Id": sf_id,
                "Status__c": "Pending",
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Template_Id__c": "t1",
            }
        }

        input_svc = FakeInputService(canonical_job_id=job_id)
        # Injected: GEN-02 only. GEN-03 (generator) is None.
        worker = GenerationWorker(
            data_root=data_root,
            gateway=gateway,
            engine=engine,
            input_service=input_svc,
            generator=None,
        )

        report = worker.run_once()
        assert report.exit_code == 4  # Blocked
        assert report.scanned_requests == 1
        assert report.admitted_requests == 1
        assert report.blocked_requests == 1
        assert len(report.pending_reasons) == 1
        assert any("GEN-03 draft generator absent" in r for r in report.pending_reasons.values())

    def test_worker_run_once_full_pipeline_completes_exit_code_0(self, test_env) -> None:
        data_root, engine = test_env
        gateway = FakeSalesforceGatewayV2()

        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {
                "Id": sf_id,
                "Status__c": "Pending",
                "Job__c": str(job_id),
                "Document_Type__c": "cv",
                "Template_Id__c": "t1",
            }
        }

        input_svc = FakeInputService(canonical_job_id=job_id)
        rend = FakeRendererDelivery()
        worker = GenerationWorker(
            data_root=data_root,
            gateway=gateway,
            engine=engine,
            input_service=input_svc,
            generator=FakeGenerator(),
            validator=FakeValidator(),
            renderer=rend,
            deliverer=rend,
        )

        report = worker.run_once()
        assert report.exit_code == 0
        assert report.scanned_requests == 1
        assert report.completed_requests == 1
        assert report.blocked_requests == 0

        # Assert remote record is Ready_for_Review
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Ready_for_Review"

    def test_worker_run_once_lock_busy_returns_exit_code_3(self, test_env) -> None:
        data_root, engine = test_env
        gateway = FakeSalesforceGatewayV2()

        # Hold the lock with another token
        lock = WindowsWorkerLock(data_root)
        token = lock.acquire_lock(owner_kind=OwnerKind.SEARCH)
        try:
            worker = GenerationWorker(
                data_root=data_root,
                gateway=gateway,
                engine=engine,
            )
            report = worker.run_once()
            assert report.exit_code == 3
            assert len(report.errors) > 0
            assert "Deployment worker lock busy" in report.errors[0].message
        finally:
            token.release()

    def test_worker_watch_mode_bounded_iterations(self, test_env) -> None:
        data_root, engine = test_env
        gateway = FakeSalesforceGatewayV2()
        settings = GenerationSettings(watch_poll_interval_seconds=1.0)

        worker = GenerationWorker(
            data_root=data_root,
            gateway=gateway,
            engine=engine,
            settings=settings,
        )

        # Runs 2 cycles and stops cleanly
        worker.run_watch(max_iterations=2)

    def test_worker_report_safe_formatting(self) -> None:
        now_utc = datetime.now(timezone.utc)
        report = GenerationWorkerReport(
            worker_attempt_id=uuid.uuid4(),
            started_at=now_utc,
            completed_at=now_utc,
            exit_code=4,
            scanned_requests=5,
            admitted_requests=3,
            reused_requests=1,
            completed_requests=1,
            blocked_requests=2,
            failed_requests=0,
            pending_reasons={"req-123": "GEN-03 draft generator absent"},
            errors=[
                ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Safe validation issue message",
                )
            ],
            recovery_actions=["Reconciled projection intent 1"],
        )

        # Human-readable formatting
        text = format_worker_report(report, as_json=False)
        assert "Generation Worker Report" in text
        assert "Exit Code:            4" in text
        assert "Scanned Requests:   5" in text
        assert "GEN-03 draft generator absent" in text
        assert "Safe validation issue message" in text

        # JSON formatting
        json_str = format_worker_report(report, as_json=True)
        data = json.loads(json_str)
        assert data["exit_code"] == 4
        assert data["blocked_requests"] == 2
