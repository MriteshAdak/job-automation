"""Contract and model validation tests for SYNC-01 (SYNC-01-S01)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
)
from job_automation.salesforce.sync_records import (
    CandidateFieldSnapshot,
    EntityType,
    PublicationDecision,
    PublicationPurpose,
    RemoteEntityMapping,
    SyncPlan,
    SyncStepState,
    SyncSubmission,
    SyncWriteStep,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "salesforce" / "sync"


def load_c11_fixture(filename: str) -> Assessment:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Assessment.model_validate(data)


class TestSyncContracts:
    def test_sync_submission_with_rules_only_assessment(self) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-token-1",
            publication_purpose=PublicationPurpose.PRIMARY_FINAL,
            job_title="Senior Python Architect",
            company_name="Cloud Corp GmbH",
            canonical_company_id=uuid.uuid4(),
            source_urls=["https://example.com/job/1"],
            availability=PostingAvailability.ACTIVE,
        )

        assert sub.assessment.assessment_method == AssessmentMethod.RULES
        assert sub.assessment.model_metadata is None
        assert sub.assessment.relevance_score is None
        assert sub.publication_purpose == PublicationPurpose.PRIMARY_FINAL

        # Verify round-trip
        dumped = sub.model_dump(mode="json")
        reloaded = SyncSubmission.model_validate(dumped)
        assert reloaded == sub

    def test_sync_submission_with_llm_assessment(self) -> None:
        asm = load_c11_fixture("llm_eligible.json")
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=asm.canonical_job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-token-2",
            publication_purpose=PublicationPurpose.PRIMARY_FINAL,
            job_title="Lead AI Engineer",
            company_name="NextGen Labs",
            canonical_company_id=uuid.uuid4(),
            source_urls=["https://example.com/job/2"],
            availability=PostingAvailability.ACTIVE,
        )

        assert sub.assessment.assessment_method == AssessmentMethod.LLM
        assert sub.assessment.model_metadata is not None
        assert sub.assessment.relevance_score == 92.5
        assert sub.assessment.score_scale == "0-100"

        dumped = sub.model_dump(mode="json")
        reloaded = SyncSubmission.model_validate(dumped)
        assert reloaded == sub

    def test_sync_submission_mismatched_canonical_id_raises(self) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        other_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        with pytest.raises(ValidationError, match="does not match submission canonical_job_id"):
            SyncSubmission(
                assessment=asm,
                canonical_job_id=other_id,  # Mismatched!
                posting_revision=asm.posting_revision,
                evaluated_at=now_dt,
                generation_token="gen-token-1",
                company_name="Acme",
            )

    def test_sync_submission_mismatched_revision_raises(self) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        now_dt = datetime.now(timezone.utc)

        with pytest.raises(ValidationError, match="does not match submission posting_revision"):
            SyncSubmission(
                assessment=asm,
                canonical_job_id=asm.canonical_job_id,
                posting_revision="sha256:different_revision_hash",  # Mismatched!
                evaluated_at=now_dt,
                generation_token="gen-token-1",
                company_name="Acme",
            )

    def test_sync_write_step_and_plan_round_trip(self) -> None:
        plan_id = uuid.uuid4()
        step_id = uuid.uuid4()
        job_id = uuid.uuid4()
        comp_id = uuid.uuid4()

        step = SyncWriteStep(
            step_id=step_id,
            plan_id=plan_id,
            entity_type=EntityType.JOB,
            entity_id=job_id,
            sequence_number=1,
            target_object="Job__c",
            external_id_field="Canonical_Job_Id__c",
            external_id_value=str(job_id),
            relationship_field="Company__c",
            frozen_payload={"Name": "Backend Dev", "Assessment_Disposition__c": "Eligible"},
            step_fingerprint="sha256:stepfp123",
            state=SyncStepState.PENDING,
            reconciliation_marker="marker-123",
        )

        plan = SyncPlan(
            plan_id=plan_id,
            canonical_job_id=job_id,
            assessment_id=uuid.uuid4(),
            mapping_version="1.0",
            mapping_hash="sha256:maphash123",
            plan_fingerprint="sha256:planfp123",
            selection_token="token-1",
            publication_decision=PublicationDecision.PUBLISH_INITIAL,
            created_at=datetime.now(timezone.utc),
            steps=[step],
        )

        dumped = plan.model_dump(mode="json")
        reloaded = SyncPlan.model_validate(dumped)
        assert reloaded == plan
        assert len(reloaded.steps) == 1
        assert reloaded.steps[0].sequence_number == 1
        assert reloaded.steps[0].entity_type == EntityType.JOB

    def test_remote_entity_mapping_round_trip(self) -> None:
        mapping = RemoteEntityMapping(
            org_id="00D000000000001",
            object_name="Job__c",
            entity_id=uuid.uuid4(),
            external_id="ext-job-123",
            salesforce_id="a00000000000001AAA",
            confirmed_sequence=3,
            reconciliation_marker="marker-999",
            acknowledged_at=datetime.now(timezone.utc),
        )

        dumped = mapping.model_dump(mode="json")
        reloaded = RemoteEntityMapping.model_validate(dumped)
        assert reloaded == mapping

    def test_candidate_field_snapshot_round_trip(self) -> None:
        snap = CandidateFieldSnapshot(
            snapshot_id=uuid.uuid4(),
            org_id="00D000000000001",
            canonical_job_id=uuid.uuid4(),
            remote_record_id="a00000000000001AAA",
            mapping_version="1.0",
            snapshot_hash="sha256:snaphsh",
            candidate_fields={
                "Application_Progress__c": "Interviewing",
                "Candidate_Notes__c": "Technical round completed, follow up on Tuesday",
                "Candidate_Decision__c": "Shortlisted",
                "Interview_Date__c": "2026-11-05",
            },
            source_modification_token="mod-etag-123",
            observed_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        dumped = snap.model_dump(mode="json")
        reloaded = CandidateFieldSnapshot.model_validate(dumped)
        assert reloaded == snap
        assert reloaded.candidate_fields["Application_Progress__c"] == "Interviewing"

