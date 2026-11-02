"""Command-line interface tests for AUTO-03 delivery subcommands."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from job_automation.cli import main
from job_automation.contracts.enums import RunStatus
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.reporting import RunReport
from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
)
from job_automation.orchestration.summary_delivery.records import (
    DeliveryAttemptRecord,
    DeliveryState,
    NotificationState,
    SummaryDelivery,
)
from job_automation.orchestration.summary_delivery.service import SummaryDeliveryService
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def cli_env(tmp_path: Path) -> tuple[Path, StorageEngine]:
    FakeSalesforceSummaryTargetAdapter.clear_shared()
    data_dir = tmp_path / "Runtime Data"
    db_path = data_dir / "database" / "job_automation.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sd_cfg = tmp_path / "summary_delivery.json"
    sd_cfg.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "enabled": True,
                "salesforce_org_id": "00D000000000001",
                "test_recipient": "test_engineer@example.com",
            }
        ),
        encoding="utf-8",
    )

    app_cfg = tmp_path / "app.json"
    app_cfg.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "app_name": "JobAutomation",
                "data_root": str(data_dir),
                "display_timezone": "Europe/Berlin",
                "model_service_url": "http://127.0.0.1:11434",
                "summary_delivery_settings_ref": str(sd_cfg),
            }
        ),
        encoding="utf-8",
    )

    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return app_cfg, engine


class TestDeliveryCli:
    def test_cli_delivery_status(self, cli_env: tuple[Path, StorageEngine], capsys: pytest.CaptureFixture[str]) -> None:
        cfg_file, _ = cli_env

        # 1. Human-readable text format
        code = main(["delivery", "status", "--config", str(cfg_file)])
        assert code == 0
        captured = capsys.readouterr()
        assert "AUTO-03 SUMMARY DELIVERY STATUS" in captured.out
        assert "Enabled:             YES" in captured.out
        assert "Salesforce Org ID:   00D000000000001" in captured.out
        assert "test_engineer@example.com" in captured.out

        # 2. JSON format
        code_json = main(["delivery", "status", "--config", str(cfg_file), "--json"])
        assert code_json == 0
        captured_json = capsys.readouterr()
        data = json.loads(captured_json.out)
        assert data["enabled"] is True
        assert data["salesforce_org_id"] == "00D000000000001"
        assert "pending" in data["queue_counts"]

    def test_cli_delivery_show_and_list(
        self,
        cli_env: tuple[Path, StorageEngine],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_file, storage = cli_env
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Populate a delivery record
        delivery = SummaryDelivery(
            run_id=run_id,
            org_id="00D000000000001",
            completion_key=f"00D000000000001:{run_id}",
            revision=1,
            state=DeliveryState.DELIVERED,
            target_object="Run_Summary__c",
            target_external_id_field="Run_Id__c",
            payload_json=json.dumps({"run_id": str(run_id)}),
            payload_hash="hash_abc",
            first_completion_hash="hash_abc",
            dispatch_attempts=1,
            retry_window_start=now,
            retry_deadline=now,
            remote_record_id="a05TestRecord123",
            notification_state=NotificationState.CONFIRMED,
            acknowledged_at=now,
        )
        storage.summary_deliveries.save_delivery(delivery)

        # Add an attempt audit
        attempt = DeliveryAttemptRecord(
            delivery_id=delivery.delivery_id,
            run_id=run_id,
            attempt_sequence=1,
            operation_kind="upsert",
            status="succeeded",
            http_status=201,
            duration_ms=85.2,
            remote_outcome="acknowledged",
        )
        storage.summary_deliveries.save_attempt(attempt)

        # Test delivery list
        code_list = main(["delivery", "list", "--config", str(cfg_file)])
        assert code_list == 0
        out_list = capsys.readouterr().out
        assert str(run_id) in out_list
        assert "delivered" in out_list

        # Test delivery show (text)
        code_show = main(["delivery", "show", "--run-id", str(run_id), "--config", str(cfg_file)])
        assert code_show == 0
        out_show = capsys.readouterr().out
        assert f"Run ID:              {run_id}" in out_show
        assert "DELIVERED" in out_show
        assert "a05TestRecord123" in out_show
        assert "CONFIRMED" in out_show
        assert "#1   upsert          [SUCCEEDED]" in out_show

        # Test delivery show (json)
        code_show_json = main(["delivery", "show", "--run-id", str(run_id), "--config", str(cfg_file), "--json"])
        assert code_show_json == 0
        data = json.loads(capsys.readouterr().out)
        assert data["run_id"] == str(run_id)
        assert data["remote_record_id"] == "a05TestRecord123"
        assert len(data["attempts"]) == 1

    def test_cli_delivery_drain_and_reconcile(
        self,
        cli_env: tuple[Path, StorageEngine],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_file, storage = cli_env
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Populate a pending delivery
        delivery = SummaryDelivery(
            run_id=run_id,
            org_id="00D000000000001",
            completion_key=f"00D000000000001:{run_id}",
            revision=1,
            state=DeliveryState.PENDING,
            target_object="Run_Summary__c",
            target_external_id_field="Run_Id__c",
            payload_json=json.dumps(
                {
                    "mapping_version": "1.0",
                    "org_id": "00D000000000001",
                    "run_id": str(run_id),
                    "completion_key": f"00D000000000001:{run_id}",
                    "revision": 1,
                    "start_time": now.isoformat(),
                    "end_time": now.isoformat(),
                    "duration_seconds": 1.0,
                    "pipeline_status": "success",
                    "headline": "Search Complete — 10 postings",
                    "summary_text": "Summary text",
                    "source_postings_count": 10,
                    "canonical_jobs_new": 2,
                    "canonical_jobs_updated": 0,
                    "canonical_jobs_duplicate": 8,
                    "eligible_count": 1,
                    "review_count": 0,
                    "rejected_count": 1,
                    "sync_succeeded": 1,
                    "sync_failed": 0,
                    "quarantined_count": 0,
                    "sources_attempted": ["arbeitnow"],
                    "sources_succeeded": ["arbeitnow"],
                    "sources_failed": [],
                    "first_result_snapshot_hash": "hash1",
                    "current_revision_hash": "hash1",
                    "is_first_completion": True,
                    "truncated": False,
                }
            ),
            payload_hash="hash1",
            first_completion_hash="hash1",
            dispatch_attempts=0,
            retry_window_start=now,
            retry_deadline=now + timedelta(hours=48),
            next_due_at=now,
        )
        storage.summary_deliveries.save_delivery(delivery)

        # 1. Drain deliveries
        code_drain = main(["delivery", "drain", "--config", str(cfg_file)])
        assert code_drain == 0
        out_drain = capsys.readouterr().out
        assert "Drained 1 delivery records:" in out_drain
        assert "state=delivered" in out_drain

        # 2. Reconcile delivery
        code_rec = main(["delivery", "reconcile", "--run-id", str(run_id), "--config", str(cfg_file)])
        assert code_rec == 0
        out_rec = capsys.readouterr().out
        assert f"Reconciled run {run_id} -> state=delivered" in out_rec

    def test_cli_delivery_retry(
        self,
        cli_env: tuple[Path, StorageEngine],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_file, storage = cli_env
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        delivery = SummaryDelivery(
            run_id=run_id,
            org_id="00D000000000001",
            completion_key=f"00D000000000001:{run_id}",
            revision=1,
            state=DeliveryState.EXHAUSTED,
            target_object="Run_Summary__c",
            target_external_id_field="Run_Id__c",
            payload_json=json.dumps({"run_id": str(run_id)}),
            payload_hash="hash1",
            first_completion_hash="hash1",
            dispatch_attempts=5,
            retry_window_start=now,
            retry_deadline=now,
        )
        storage.summary_deliveries.save_delivery(delivery)

        # Retry reset
        code = main(["delivery", "retry", "--run-id", str(run_id), "--config", str(cfg_file)])
        assert code == 0
        out = capsys.readouterr().out
        assert f"Reset retry for run {run_id}: state=reconcile_required" in out

        updated = storage.summary_deliveries.get_delivery("00D000000000001", run_id)
        assert updated is not None
        assert updated.state == DeliveryState.RECONCILE_REQUIRED
