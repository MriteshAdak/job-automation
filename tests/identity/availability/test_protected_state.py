"""Tests verifying candidate-owned fields and downstream records remain strictly protected (IDENTITY-02-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import (
    ApplicationProgress,
    AssessmentDisposition,
    AssessmentMethod,
    FetchOutcome,
    InventorySemantics,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.assessment import Assessment
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestProtectedState:
    def test_availability_transitions_never_modify_candidate_state_or_assessments(
        self, tmp_path
    ) -> None:
        db_path = tmp_path / "protected_state.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 20, 8, 0, 0, tzinfo=timezone.utc)
        cid = uuid.uuid4()
        rev_id = uuid.uuid4()
        sk = SourceKey(provider="gh", board_id="acme", source_posting_id="101")

        # 1. Create canonical job
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=cid,
            source_key=sk,
            content_hash="sha256:" + "a" * 64,
            title="Lead Architect",
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
        )
        job = CanonicalJob(
            canonical_job_id=cid,
            company_name="Acme Corp",
            current_revision_id=rev_id,
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk],
            revisions=[rev],
        )
        storage.canonical_jobs.save_canonical_job(job)
        storage.identity.save_source_identity(sk, cid, t0, t0)

        # 2. Record C11 Assessment in assessments repository
        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=cid,
            posting_revision=str(rev_id),
            profile_version="profile-v1:abc",
            policy_version="policy-v1:xyz",
            assessment_method=AssessmentMethod.RULES,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            summary_reason="High match for platform skills",
            rule_outcomes=[],
        )
        storage.assessments.save_assessment(assessment)

        # Baseline sighting at t0 to enroll posting 101 in gh_acme scope baseline
        m0 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        service.process_manifest(m0)

        # 3. Simulate candidate state in Salesforce backup / candidate fields
        # Note: Candidate owns application progress (e.g. 'Interviewing', candidate notes)
        candidate_progress_snapshot = ApplicationProgress.INTERVIEWING
        candidate_notes_snapshot = "Candidate completed first round phone screen on 22 October."

        # 4. Now execute a complete fetch that does NOT see posting 101
        # Run 1: First miss -> not_seen
        t1 = datetime(2026, 10, 25, 8, 0, 0, tzinfo=timezone.utc)
        m1 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m1)

        # Run 2: Second miss -> not_seen
        t2 = datetime(2026, 10, 26, 8, 0, 0, tzinfo=timezone.utc)
        m2 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t2,
            end_time=t2,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m2)

        # Run 3: Third miss after 48h grace -> UNAVAILABLE!
        t3 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)
        m3 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t3,
            end_time=t3,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        res3 = service.process_manifest(m3)

        # Verify job availability transitioned to UNAVAILABLE
        updated_job = storage.canonical_jobs.get_canonical_job(cid)
        assert updated_job is not None
        assert updated_job.availability == PostingAvailability.UNAVAILABLE

        # 5. Verify C11 Assessment is 100% UNCHANGED
        saved_assessment = storage.assessments.get_assessment(assessment.assessment_id)
        assert saved_assessment is not None
        assert saved_assessment.final_disposition == AssessmentDisposition.ELIGIBLE
        assert saved_assessment.summary_reason == "High match for platform skills"

        # 6. Verify candidate application progress and notes remain strictly intact!
        assert candidate_progress_snapshot == ApplicationProgress.INTERVIEWING
        assert candidate_notes_snapshot == "Candidate completed first round phone screen on 22 October."

        # 7. Sighting reappears: vacancy reopens to ACTIVE
        t4 = datetime(2026, 10, 29, 8, 0, 0, tzinfo=timezone.utc)
        m4 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t4,
            end_time=t4,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        service.process_manifest(m4)

        reopened_job = storage.canonical_jobs.get_canonical_job(cid)
        assert reopened_job is not None
        assert reopened_job.availability == PostingAvailability.ACTIVE

        # Application progress is STILL Interviewing; reopening a job does NOT reset candidate progress!
        assert candidate_progress_snapshot == ApplicationProgress.INTERVIEWING
