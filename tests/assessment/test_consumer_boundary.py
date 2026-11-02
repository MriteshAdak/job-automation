"""Consumer boundary tests for C11 Assessment records (MATCH-01-S06, S07).

Verifies that:
1. Assessments produced by deterministic evaluation persist and round-trip via AssessmentRepository.
2. C11 outputs cleanly map into C12 SyncPayload and SyncOperation without model metadata.
3. Candidate-owned fields (application progress, candidate notes) are strictly excluded from sync payloads.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from job_automation.assessment.inputs import bind_assessment_input
from job_automation.assessment.service import evaluate_deterministic
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
    SalaryPeriod,
    SyncOperationState,
    WorkplaceType,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.policy import HardCriterion
from job_automation.contracts.postings import JobCompensation
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.storage.engine import StorageEngine


class TestConsumerBoundary:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "consumer_test.db"
        raw_dir = tmp_path / "raw"
        artifacts_dir = tmp_path / "artifacts"
        eng = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=artifacts_dir)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_assessment_persists_and_roundtrips_cleanly(
        self, engine: StorageEngine, make_posting, make_profile, make_policy
    ) -> None:
        comp = JobCompensation(
            min_amount=Decimal("65000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        posting = make_posting(
            title="Python Backend Developer",
            country="DE",
            city="Berlin",
            workplace_type=WorkplaceType.REMOTE,
            remote_restrictions=["DE"],
            compensation=comp,
        )
        profile = make_profile()
        policy = make_policy(
            hard_criteria=[
                HardCriterion(
                    criterion_id="crit_country",
                    name="Location DE",
                    field="locations.country",
                    operator="equals",
                    expected_value="DE",
                )
            ],
            broad_keywords=["Python", "Backend"],
        )

        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        canonical_job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Tech Solutions GmbH",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(canonical_job)

        inp = bind_assessment_input(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )

        assessment = evaluate_deterministic(inp)
        assert assessment.final_disposition == AssessmentDisposition.ELIGIBLE
        assert assessment.assessment_method == AssessmentMethod.RULES
        assert assessment.model_metadata is None

        # Save to repository
        engine.assessments.save_assessment(assessment)

        # Retrieve and verify round-trip
        loaded = engine.assessments.get_assessment(assessment.assessment_id)
        assert loaded is not None
        assert loaded.assessment_id == assessment.assessment_id
        assert loaded.canonical_job_id == job_id
        assert loaded.final_disposition == AssessmentDisposition.ELIGIBLE
        assert loaded.summary_reason == assessment.summary_reason
        assert loaded.rule_outcomes == assessment.rule_outcomes
        assert loaded.model_dump() == assessment.model_dump()

        # Check get_latest_assessment
        latest = engine.assessments.get_latest_assessment(job_id)
        assert latest is not None
        assert latest.assessment_id == assessment.assessment_id

    def test_c11_conversion_to_c12_sync_payload_preserves_candidate_owned_fields(
        self, make_posting, make_profile, make_policy
    ) -> None:
        posting = make_posting(
            title="Senior Python Engineer",
            description="Seeking Senior Python Engineer for cloud platforms.",
        )
        profile = make_profile()
        policy = make_policy(broad_keywords=["Python", "Cloud"])

        job_id = uuid.uuid4()
        inp = bind_assessment_input(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )
        assessment = evaluate_deterministic(inp)

        now_dt = datetime.now(timezone.utc)
        payload = SyncPayload(
            canonical_job_id=assessment.canonical_job_id,
            job_title=posting.title,
            company_name=posting.company_name_hint or "Unknown",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=assessment.final_disposition,
            relevance_score=assessment.relevance_score,  # None for deterministic
            score_scale=assessment.score_scale,  # None
            assessment_reasons=assessment.summary_reason,
            source_urls=[posting.source_url],
            last_evaluated_at=now_dt,
        )

        assert payload.relevance_score is None
        assert payload.score_scale is None
        assert payload.assessment_disposition == AssessmentDisposition.ELIGIBLE
        assert payload.canonical_job_id == job_id

        # Candidate-owned fields must NOT exist in SyncPayload schema
        candidate_owned_fields = {
            "application_status",
            "candidate_notes",
            "interview_date",
            "follow_up_date",
            "manual_override",
            "resume_version",
        }
        payload_fields = set(SyncPayload.model_fields.keys())
        assert payload_fields.isdisjoint(candidate_owned_fields)

        # Build SyncOperation
        raw_bytes = payload.model_dump_json().encode("utf-8")
        fingerprint = hashlib.sha256(raw_bytes).hexdigest()
        op = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=job_id,
            payload_version="v1",
            payload_fingerprint=fingerprint,
            locally_owned_payload=payload,
            attempt_count=0,
            max_attempts=3,
            state=SyncOperationState.PENDING,
        )

        assert op.state == SyncOperationState.PENDING
        assert op.locally_owned_payload.assessment_disposition == AssessmentDisposition.ELIGIBLE
        assert op.locally_owned_payload.relevance_score is None
