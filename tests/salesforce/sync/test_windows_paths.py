"""Tests for native Windows paths with spaces and non-ASCII characters (SYNC-01-S09)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.sync_dispatch import SyncDispatcher
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationDecision,
    SyncStepState,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.salesforce.sync.test_publication import load_c11_fixture

ORIGINAL_CONFIG = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


class TestWindowsPaths:
    def test_windows_paths_with_spaces_and_umlauts(self, tmp_path: Path) -> None:
        """Verify storage engine and config loader work on Windows paths with spaces and umlauts."""
        # Create directory with spaces, German umlauts and special characters
        unicode_dir = tmp_path / "Job Automation Prüfung für Entwickler äöüß" / "Datenbank Ordner"
        unicode_dir.mkdir(parents=True, exist_ok=True)

        db_path = unicode_dir / "sync_prüfung.db"
        config_path = unicode_dir / "sync_konfig.json"

        # Copy original config to unicode path
        with open(ORIGINAL_CONFIG, "r", encoding="utf-8") as f:
            cfg_data = json.load(f)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg_data, f, indent=2)

        # 1. Load config from path with spaces and umlauts
        config = load_sync_mapping_config(config_path)
        assert config.expected_org_id == "00D000000000001"

        # 2. Initialize StorageEngine at unicode path
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        # Check WAL mode on Windows
        cursor = engine.conn.execute("PRAGMA journal_mode;")
        journal_mode = cursor.fetchone()[0].lower()
        assert journal_mode == "wal"

        # 3. Seed canonical job and commit sync plan
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=comp_id,
            company_name="München Software AG",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-win-paths",
            job_title="Softwareentwickler für Cloud-Lösungen",
            company_name="München Software AG",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )
        service = SyncService(engine)
        plan_res = service.commit_assessment_and_plan(sub, config)

        assert plan_res.is_published is True
        assert len(plan_res.plan.steps) == 2

        # 4. Dispatch using gateway
        gateway = FakeSalesforceGatewayV2()
        dispatcher = SyncDispatcher(engine)
        drain = dispatcher.drain_due_work(gateway, config)

        assert drain.steps_succeeded == 2
        assert gateway.physical_upsert_count == 2

        # 5. Clean close to ensure file handle release on Windows
        engine.close()
        assert db_path.exists()

