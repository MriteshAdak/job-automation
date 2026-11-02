"""Publication eligibility and decision tests for SYNC-01 (SYNC-01-S04)."""

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
    PublicationPurpose,
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


class TestPublicationDecisions:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_pub_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    def _ensure_canonical_job(
        self,
        engine: StorageEngine,
        job_id: uuid.UUID,
        company_name: str = "Cloud Corp",
        company_id: uuid.UUID | None = None,
    ) -> None:
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name=company_name,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

    def test_new_eligible_job_publishes_initial(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)
        comp_id = uuid.uuid4()
        self._ensure_canonical_job(engine, asm.canonical_job_id, "Cloud Corp", comp_id)

        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            job_title="Senior Python Architect",
            company_name="Cloud Corp",
            canonical_company_id=comp_id,
            source_urls=["https://example.com/job/1"],
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        result = service.commit_assessment_and_plan(sub, config)

        assert result.is_published is True
        assert result.publication_decision == PublicationDecision.PUBLISH_INITIAL
        assert result.sync_operation is not None
        assert result.sync_operation.locally_owned_payload.assessment_disposition == AssessmentDisposition.ELIGIBLE
        assert len(result.plan.steps) == 2  # Company step + Job step
        assert result.plan.steps[0].target_object == config.company_object
        assert result.plan.steps[1].target_object == config.job_object
        assert result.plan.steps[1].depends_on_step_id == result.plan.steps[0].step_id

    def test_new_rejected_job_rules_only_stays_local_without_publishing(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_rejected.json")
        now_dt = datetime.now(timezone.utc)
        self._ensure_canonical_job(engine, asm.canonical_job_id, "US Only Inc")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-rej-1",
            job_title="Software Dev",
            company_name="US Only Inc",
            canonical_company_id=uuid.uuid4(),
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        result = service.commit_assessment_and_plan(sub, config)

        assert result.is_published is False
        assert result.publication_decision == PublicationDecision.LOCAL_ONLY_REJECTED
        assert result.sync_operation is None
        assert len(result.plan.steps) == 0

        # Assessment is durably persisted locally
        saved_asm = engine.assessments.get_assessment(asm.assessment_id)
        assert saved_asm is not None
        assert saved_asm.final_disposition == AssessmentDisposition.REJECTED

        # No sync operation in outbox
        pending_ops = engine.sync_outbox.get_pending_operations()
        assert len(pending_ops) == 0

    def test_new_rejected_job_llm_stays_local_without_publishing(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("llm_rejected.json")
        now_dt = datetime.now(timezone.utc)
        self._ensure_canonical_job(engine, asm.canonical_job_id, "Legacy Systems")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-rej-llm",
            job_title="COBOL Specialist",
            company_name="Legacy Systems",
            canonical_company_id=uuid.uuid4(),
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        result = service.commit_assessment_and_plan(sub, config)

        assert result.is_published is False
        assert result.publication_decision == PublicationDecision.LOCAL_ONLY_REJECTED
        assert result.sync_operation is None
        assert len(result.plan.steps) == 0

        # Saved locally
        saved_asm = engine.assessments.get_assessment(asm.assessment_id)
        assert saved_asm is not None

    def test_tracked_job_later_rejected_receives_update_without_losing_history(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm_rej = load_c11_fixture("rules_only_rejected.json")
        job_id = asm_rej.canonical_job_id
        comp_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        self._ensure_canonical_job(engine, job_id, "US Only Inc", comp_id)

        # Pre-seed remote mapping to indicate this job is ALREADY tracked in Salesforce
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

        # Pre-seed company mapping
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

        sub = SyncSubmission(
            assessment=asm_rej,
            canonical_job_id=job_id,
            posting_revision=asm_rej.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-update-1",
            job_title="Software Dev",
            company_name="US Only Inc",
            canonical_company_id=comp_id,
            availability=PostingAvailability.ACTIVE,
        )

        service = SyncService(engine)
        result = service.commit_assessment_and_plan(sub, config)

        # Because job is tracked, rejection MUST be published as an update!
        assert result.is_published is True
        assert result.publication_decision == PublicationDecision.UPDATE_TRACKED
        assert result.sync_operation is not None
        assert result.sync_operation.locally_owned_payload.assessment_disposition == AssessmentDisposition.REJECTED
        assert len(result.plan.steps) == 1  # Only Job step (Company is already mapped)
        job_step = result.plan.steps[0]
        assert job_step.sequence_number == 1  # Next sequence for this job
        assert job_step.frozen_payload[config.disposition_field] == "Rejected"
        assert job_step.frozen_payload[config.job_company_lookup_field] == "a01CompRemoteId01"

    def test_comparison_submission_stays_local(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("llm_eligible.json")
        now_dt = datetime.now(timezone.utc)
        self._ensure_canonical_job(engine, asm.canonical_job_id, "NextGen Labs")
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-comp",
            publication_purpose=PublicationPurpose.COMPARISON,  # Evaluation/comparison!
            job_title="Lead AI Engineer",
            company_name="NextGen Labs",
            canonical_company_id=uuid.uuid4(),
        )

        service = SyncService(engine)
        result = service.commit_assessment_and_plan(sub, config)

        assert result.is_published is False
        assert result.publication_decision == PublicationDecision.LOCAL_ONLY_COMPARISON
        assert result.sync_operation is None
        assert len(result.plan.steps) == 0
