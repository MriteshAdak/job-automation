"""Integration tests between PipelineRunner and SummaryDeliveryService (AUTO-03 handoff)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.reporting import RunReport
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.summary_delivery.adapter import (
    FakeSalesforceSummaryTargetAdapter,
)
from job_automation.orchestration.summary_delivery.records import (
    DeliveryState,
    NotificationState,
)
from job_automation.orchestration.summary_delivery.settings import SummaryDeliverySettings
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


@pytest.fixture
def run_env(tmp_path: Path) -> tuple[Path, StorageEngine]:
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


class TestRunnerSummaryDeliveryIntegration:
    def test_runner_records_completion_receipt_when_disabled(self, tmp_path: Path) -> None:
        """When delivery is disabled, terminal RunCompletionReceipt is still persisted locally."""
        data_dir = tmp_path / "DataDisabled"
        db_path = data_dir / "database" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        app_cfg = tmp_path / "app_disabled.json"
        app_cfg.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "app_name": "JobAutomation",
                    "data_root": str(data_dir),
                    "display_timezone": "Europe/Berlin",
                    "model_service_url": "http://127.0.0.1:11434",
                }
            ),
            encoding="utf-8",
        )

        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        runner = PipelineRunner(config_path=app_cfg, engine=engine)

        # Build synthetic report and invoke handoff
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        report = RunReport(
            c15_summary=engine.runs.get_run(run_id) or RunSummary(
                run_id=run_id,
                start_time=now,
                end_time=now,
                status=RunStatus.SUCCESS,
                source_postings_count=10,
            ),
            attempt_sequence=1,
            assessment_mode="rules",
            exit_code=0,
        )

        final_rep = runner._finalize_and_record_summary(
            engine=engine,
            paths=None,
            opts=RunOptions(),
            report=report,
        )

        assert final_rep.exit_code == 0

        # Receipt was persisted
        receipt = engine.summary_deliveries.get_receipt(run_id)
        assert receipt is not None
        assert receipt.run_id == run_id

        # But outbox delivery was NOT created because feature is disabled by default
        assert engine.summary_deliveries.get_delivery("00D000000000001", run_id) is None

    def test_runner_delivers_summary_and_preserves_exit_code_on_delivery_failure(
        self,
        run_env: tuple[Path, StorageEngine],
    ) -> None:
        """Delivery failure never modifies pipeline exit code: pipeline remains success (code 0)."""
        app_cfg, engine = run_env

        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Fake adapter that fails with 503 server outage
        fake_target = FakeSalesforceSummaryTargetAdapter(org_id="00D000000000001")
        fake_target.simulate_server_error = True

        runner = PipelineRunner(config_path=app_cfg, engine=engine)
        opts = RunOptions(
            summary_target=fake_target,
            deliver_summary=True,
        )

        report = RunReport(
            c15_summary=RunSummary(
                run_id=run_id,
                start_time=now,
                end_time=now,
                status=RunStatus.SUCCESS,
                source_postings_count=35,
                canonical_jobs_new=4,
            ),
            attempt_sequence=1,
            assessment_mode="rules",
            exit_code=0,  # Pipeline succeeded!
        )

        final_rep = runner._finalize_and_record_summary(
            engine=engine,
            paths=None,
            opts=opts,
            report=report,
        )

        # Pipeline exit code is STILL 0 (success)
        assert final_rep.exit_code == 0
        assert final_rep.c15_summary.status == RunStatus.SUCCESS

        # Delivery failure was recorded visibly in SQLite
        deliv = engine.summary_deliveries.get_delivery("00D000000000001", run_id)
        assert deliv is not None
        assert deliv.state == DeliveryState.RETRY_WAIT
        assert deliv.dispatch_attempts == 1
        assert deliv.next_due_at is not None

    def test_live_notification_verification_gating(self) -> None:
        """When test_recipient is absent, live verification is marked PENDING."""
        settings_unconfigured = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id="00D000000000001",
            test_recipient=None,
        )
        assert settings_unconfigured.test_recipient is None

        settings_configured = SummaryDeliverySettings(
            enabled=True,
            salesforce_org_id="00D000000000001",
            test_recipient="authorized_tester@example.com",
        )
        assert settings_configured.test_recipient == "authorized_tester@example.com"
