"""Transaction and atomic rollback tests for SYNC-01 storage (SYNC-01-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
    SyncOperationState,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationDecision,
    SyncPlan,
    SyncStepState,
    SyncWriteStep,
)
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError


class TestSyncTransactions:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_trans_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_atomic_commit_plan_and_steps_success(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Sync Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=job_id,
            posting_revision="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            profile_version="1.0",
            policy_version="1.0",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Meets deterministic criteria",
        )

        plan_id = uuid.uuid4()
        op_id = uuid.uuid4()
        step_id = uuid.uuid4()

        payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Software Architect",
            company_name="Sync Corp",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="Meets criteria",
            last_evaluated_at=now_dt,
        )
        sync_op = SyncOperation(
            operation_id=op_id,
            canonical_job_id=job_id,
            payload_version="1",
            payload_fingerprint="sha256:payloadfp",
            locally_owned_payload=payload,
            state=SyncOperationState.PENDING,
        )

        step = SyncWriteStep(
            step_id=step_id,
            plan_id=plan_id,
            operation_id=op_id,
            entity_type=EntityType.JOB,
            entity_id=job_id,
            sequence_number=1,
            target_object="Job__c",
            external_id_field="Canonical_Job_Id__c",
            external_id_value=str(job_id),
            relationship_field="Company__c",
            frozen_payload={"Name": "Software Architect"},
            step_fingerprint="sha256:stepfp",
            reconciliation_marker="marker-1",
        )

        plan = SyncPlan(
            plan_id=plan_id,
            canonical_job_id=job_id,
            assessment_id=assessment.assessment_id,
            mapping_version="1.0",
            mapping_hash="sha256:maphash",
            plan_fingerprint="sha256:planfp",
            selection_token="token-1",
            publication_decision=PublicationDecision.PUBLISH_INITIAL,
            created_at=now_dt,
            steps=[step],
        )

        engine.sync_state.commit_plan_and_steps(plan, sync_op=sync_op, assessment=assessment)

        # Verify all records exist
        saved_plan = engine.sync_state.get_plan(plan_id)
        assert saved_plan is not None
        assert saved_plan.plan_id == plan_id
        assert len(saved_plan.steps) == 1
        assert saved_plan.steps[0].step_id == step_id

        saved_asm = engine.assessments.get_assessment(assessment.assessment_id)
        assert saved_asm is not None

        saved_op = engine.sync_outbox.get_operation(op_id)
        assert saved_op is not None

    def test_atomic_commit_plan_rollback_on_step_duplicate(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Sync Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        asm_id_1 = uuid.uuid4()
        assessment_1 = Assessment(
            assessment_id=asm_id_1,
            canonical_job_id=job_id,
            posting_revision="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            profile_version="1.0",
            policy_version="1.0",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Meets deterministic criteria",
        )

        plan_id_1 = uuid.uuid4()
        step_1 = SyncWriteStep(
            step_id=uuid.uuid4(),
            plan_id=plan_id_1,
            entity_type=EntityType.JOB,
            entity_id=job_id,
            sequence_number=1,
            target_object="Job__c",
            external_id_field="Canonical_Job_Id__c",
            external_id_value=str(job_id),
            frozen_payload={"Name": "Dev"},
            step_fingerprint="sha256:fp1",
            reconciliation_marker="marker-1",
        )
        plan_1 = SyncPlan(
            plan_id=plan_id_1,
            canonical_job_id=job_id,
            assessment_id=asm_id_1,
            mapping_version="1.0",
            mapping_hash="sha256:maphash",
            plan_fingerprint="sha256:planfp1",
            selection_token="token-1",
            publication_decision=PublicationDecision.PUBLISH_INITIAL,
            created_at=now_dt,
            steps=[step_1],
        )
        engine.sync_state.commit_plan_and_steps(plan_1, assessment=assessment_1)

        # Now attempt to commit plan_2 with conflicting sequence 1 on same entity
        asm_id_2 = uuid.uuid4()
        assessment_2 = Assessment(
            assessment_id=asm_id_2,
            canonical_job_id=job_id,
            posting_revision="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            profile_version="1.0",
            policy_version="1.0",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Meets deterministic criteria",
        )
        plan_id_2 = uuid.uuid4()
        conflicting_step = SyncWriteStep(
            step_id=uuid.uuid4(),
            plan_id=plan_id_2,
            entity_type=EntityType.JOB,
            entity_id=job_id,
            sequence_number=1,  # Duplicate sequence on same (entity_type, entity_id)!
            target_object="Job__c",
            external_id_field="Canonical_Job_Id__c",
            external_id_value=str(job_id),
            frozen_payload={"Name": "Dev 2"},
            step_fingerprint="sha256:fp2",
            reconciliation_marker="marker-2",
        )
        plan_2 = SyncPlan(
            plan_id=plan_id_2,
            canonical_job_id=job_id,
            assessment_id=asm_id_2,
            mapping_version="1.0",
            mapping_hash="sha256:maphash",
            plan_fingerprint="sha256:planfp2",
            selection_token="token-2",
            publication_decision=PublicationDecision.PUBLISH_INITIAL,
            created_at=now_dt,
            steps=[conflicting_step],
        )

        with pytest.raises(DuplicateKeyError):
            engine.sync_state.commit_plan_and_steps(plan_2, assessment=assessment_2)

        # Entire plan_2 and assessment_2 must have rolled back!
        assert engine.sync_state.get_plan(plan_id_2) is None
        assert engine.assessments.get_assessment(asm_id_2) is None

