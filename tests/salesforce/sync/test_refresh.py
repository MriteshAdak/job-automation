"""Tracked job availability refresh tests for SYNC-01 (SYNC-01-S04)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.salesforce.sync_records import (
    PublicationDecision,
    RemoteEntityMapping,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "salesforce" / "sync"
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


def load_c11_fixture(filename: str) -> Assessment:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Assessment.model_validate(data)


class TestTrackedRefresh:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_refresh_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    def test_queue_tracked_refresh_closed_job(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        # 1. Save canonical job and initial assessment in storage
        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=comp_id,
            company_name="Cloud Corp",
            availability="active",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)
        engine.assessments.save_assessment(asm)

        # 2. Pre-seed remote mapping to indicate tracked status in Salesforce
        job_mapping = RemoteEntityMapping(
            org_id=config.expected_org_id,
            object_name=config.job_object,
            entity_id=job_id,
            external_id=str(job_id),
            salesforce_id="a00JobRemoteId001",
            confirmed_sequence=1,
            reconciliation_marker="initial-marker",
            acknowledged_at=now_dt,
        )
        engine.sync_state.save_remote_mapping(job_mapping)

        comp_mapping = RemoteEntityMapping(
            org_id=config.expected_org_id,
            object_name=config.company_object,
            entity_id=comp_id,
            external_id=str(comp_id),
            salesforce_id="a01CompRemoteId01",
            confirmed_sequence=1,
            reconciliation_marker="comp-marker",
            acknowledged_at=now_dt,
        )
        engine.sync_state.save_remote_mapping(comp_mapping)

        # 3. Job has closed on source board -> queue tracked refresh with PostingAvailability.UNAVAILABLE
        service = SyncService(engine)
        res = service.queue_tracked_refresh(
            canonical_job_id=job_id,
            new_availability=PostingAvailability.UNAVAILABLE,
            change_token="change-closure-token",
            config=config,
            run_id="run-avail-scan-1",
        )

        assert res.is_published is True
        assert res.publication_decision == PublicationDecision.UPDATE_TRACKED
        assert res.sync_operation is not None
        assert res.sync_operation.locally_owned_payload.availability == PostingAvailability.UNAVAILABLE
        assert res.sync_operation.locally_owned_payload.assessment_disposition == AssessmentDisposition.ELIGIBLE

        # Write step verification
        assert len(res.plan.steps) == 1
        job_step = res.plan.steps[0]
        assert job_step.frozen_payload[config.availability_field] == "Unavailable"
        assert job_step.frozen_payload[config.disposition_field] == "Eligible"
        assert job_step.sequence_number == 1

