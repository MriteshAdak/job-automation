"""Tests for assessment reuse and unchanged rerun zero-evaluation guarantee (RUN-01-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.assessment.service import AssessmentService
from job_automation.contracts.enums import AssessmentDisposition, PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import CandidateEligibility, ProfileApprovalMetadata, ProfileSnapshot
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import PostingBinding, RunAttempt, RunRequest
from job_automation.orchestration.selection import SelectionManager
from job_automation.storage.engine import StorageEngine


class TestAssessmentReuse:
    def test_unchanged_rerun_reuses_existing_c11_and_timestamp(self, tmp_path: Path) -> None:
        db_path = tmp_path / "asmt_reuse.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att1)

        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
        asmt_service = AssessmentService()
        sel_mgr = SelectionManager(engine)
        inval_eval = InvalidationEvaluator(engine)
        coord = AssessmentStageCoordinator(engine, asmt_service, sel_mgr, inval_eval)

        # Build synthetic profile and policy
        cand_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        profile = ProfileSnapshot(
            candidate_id=cand_id,
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="Candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(),
            evidence_records=[],
        )
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="1")
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/1",
            raw_reference="raw/1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="Tech Corp",
            title="Senior Python Developer",
            description_clean="Python dev role",
            observed_at=now,
        )
        binding = PostingBinding(
            canonical_job_id=can_id,
            revision_id=uuid.uuid4(),
            normalized_content_hash=f"sha256:{'a'*64}",
            raw_reference="raw/1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            source_key=sk,
            c06_snapshot=c06,
        )
        engine.pipeline_work.save_posting_binding(binding)

        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Tech Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=binding.revision_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[
                PostingRevision(
                    revision_id=binding.revision_id,
                    canonical_job_id=can_id,
                    source_key=sk,
                    content_hash=f"sha256:{'1'*64}",
                    title="Senior Python Developer",
                    first_seen_at=now,
                    last_seen_at=now,
                )
            ],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        # Run 1: initial assessment
        res1 = coord.execute_assessment(
            request=req,
            attempt=att1,
            bindings=[binding],
            profile=profile,
            policy=policy,
        )
        assert res1.total_evaluated == 1
        assert res1.reused_count == 0
        asmt_id_1 = res1.items[0].assessment.assessment_id
        time_1 = res1.items[0].selection.evaluated_at

        # Run 2: second invocation with unchanged inputs
        att2 = RunAttempt(run_id=run_id, attempt_sequence=2, status="running")
        engine.pipeline_work.save_run_attempt(att2)

        res2 = coord.execute_assessment(
            request=req,
            attempt=att2,
            bindings=[binding],
            profile=profile,
            policy=policy,
        )
        assert res2.total_evaluated == 0  # Zero evaluator calls!
        assert res2.reused_count == 1
        assert res2.items[0].is_reused is True
        assert res2.items[0].assessment.assessment_id == asmt_id_1  # Exact same C11 ID!
        assert res2.items[0].selection.evaluated_at == time_1  # Exact same timestamp!

        engine.close()
