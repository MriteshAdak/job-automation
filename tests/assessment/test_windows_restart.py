"""Tests for persistence across connection / process restart on Windows (MATCH-01-S08)."""

from __future__ import annotations

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
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.policy import HardCriterion
from job_automation.contracts.postings import JobCompensation
from job_automation.storage.engine import StorageEngine


class TestWindowsRestart:
    def test_assessment_persists_across_engine_restarts(
        self, tmp_path: Path, make_posting, make_profile, make_policy
    ) -> None:
        db_path = tmp_path / "restart_test.db"
        raw_dir = tmp_path / "raw"
        art_dir = tmp_path / "artifacts"

        # Session 1: Create, initialize, evaluate, and save
        engine1 = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)
        engine1.initialize_schema()

        comp = JobCompensation(
            min_amount=Decimal("80000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        posting = make_posting(
            title="Senior Python Architect",
            country="DE",
            city="Frankfurt",
            workplace_type=WorkplaceType.HYBRID,
            compensation=comp,
        )
        profile = make_profile(auth_countries=["DE"])
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
            broad_keywords=["Python", "Architect"],
        )

        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Banking Tech GmbH",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine1.canonical_jobs.save_canonical_job(job)

        inp = bind_assessment_input(
            canonical_job_id=job_id,
            posting_revision=posting.raw_content_hash,
            posting=posting,
            policy=policy,
            profile=profile,
        )
        assessment = evaluate_deterministic(inp)
        assert assessment.final_disposition == AssessmentDisposition.ELIGIBLE

        engine1.assessments.save_assessment(assessment)
        assessment_id = assessment.assessment_id

        # Explicitly close Session 1
        engine1.close()

        # Session 2: Open a fresh StorageEngine on the same SQLite file
        engine2 = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)
        try:
            loaded = engine2.assessments.get_assessment(assessment_id)
            assert loaded is not None
            assert loaded.assessment_id == assessment_id
            assert loaded.canonical_job_id == job_id
            assert loaded.final_disposition == AssessmentDisposition.ELIGIBLE
            assert loaded.assessment_method == AssessmentMethod.RULES
            assert loaded.summary_reason == assessment.summary_reason
            assert loaded.model_metadata is None

            # Verify list for job
            job_assessments = engine2.assessments.get_assessments_for_job(job_id)
            assert len(job_assessments) == 1
            assert job_assessments[0].assessment_id == assessment_id
        finally:
            engine2.close()

