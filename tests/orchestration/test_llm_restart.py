"""Tests for LLM assessment recovery and pending item handling across crashes/restarts (RUN-01-S09)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_automation.assessment.llm_records import AssessmentRunResult
from job_automation.assessment.service import AssessmentService
from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RequirementFinding,
    RuleOutcome,
)
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    PostingAvailability,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import (
    AssessmentMode,
    PostingBinding,
    RunAttempt,
    RunRequest,
    WorkItemState,
)
from job_automation.orchestration.selection import SelectionManager
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot


class TestLLMRestart:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "llm_restart.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def candidate_profile(self) -> ProfileSnapshot:
        return create_selector_test_snapshot()

    @pytest.fixture
    def passing_policy(self) -> SearchPolicy:
        return SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )

    def test_llm_assessment_failure_leaves_pending_work_and_resumes_cleanly(
        self,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """When LLM inference fails, item is marked pending; subsequent resume retries and succeeds."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att1)

        req = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="cfg_hash",
        )

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p404")
        content_hash = f"sha256:{'4'*64}"
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p404",
            raw_reference="raw/p404.json",
            raw_content_hash=content_hash,
            company_name_hint="Tech Corp",
            title="Senior Python Backend Developer",
            description_clean="Senior Python developer with cloud and database experience.",
            observed_at=now,
        )
        binding = PostingBinding(
            canonical_job_id=can_id,
            revision_id=uuid.uuid4(),
            normalized_content_hash=content_hash,
            raw_reference="raw/p404.json",
            raw_content_hash=content_hash,
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
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        # -------------------------------------------------------------
        # Attempt 1: LLM inference fails / times out
        # -------------------------------------------------------------
        mock_llm1 = MagicMock()
        mock_llm1.assess.return_value = AssessmentRunResult(
            status="pending",
            failed_stage="inference",
            error=ClassifiedError(
                category=ErrorCategory.TRANSIENT_NETWORK,
                message="Local model service socket timeout",
                recoverable=True,
            ),
            input_fingerprint="fp_attempt1",
        )

        coord1 = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm1,
        )

        res1 = coord1.execute_assessment(
            request=req,
            attempt=att1,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
        )

        # Pending item recorded, not completed
        assert len(res1.items) == 0
        assert len(res1.pending_items) == 1
        assert "LLM assessment pending" in res1.pending_items[0]

        # Verify durable pending stage work in database
        work_records = engine.pipeline_work.list_stage_work_for_run(run_id, stage_name="assess")
        assert len(work_records) == 1
        assert work_records[0].state == WorkItemState.PENDING
        assert work_records[0].error is not None
        assert work_records[0].error.category == ErrorCategory.TRANSIENT_NETWORK

        # Zero assessments saved to canonical store yet
        assert engine.assessments.get_latest_assessment(can_id) is None

        # -------------------------------------------------------------
        # Attempt 2: Resume with recovered model service
        # -------------------------------------------------------------
        att2 = RunAttempt(run_id=run_id, attempt_sequence=2, status="running")
        engine.pipeline_work.save_run_attempt(att2)

        mock_llm2 = MagicMock()
        asmt_success = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision=content_hash,
            profile_version=candidate_profile.profile_version,
            policy_version=passing_policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=[],
            requirement_findings=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=92.0,
            score_scale="0-100",
            summary_reason="Successful assessment upon retry",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=LLMAssessmentMetadata(
                model_identifier="llama3:8b",
                prompt_version="v1",
                context_strategy=ContextStrategy.JSON,
            ),
        )
        mock_llm2.assess.return_value = AssessmentRunResult(
            status="success",
            assessment=asmt_success,
            input_fingerprint="fp_attempt2",
        )

        coord2 = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm2,
        )

        res2 = coord2.execute_assessment(
            request=req,
            attempt=att2,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
        )

        assert res2.eligible_count == 1
        assert len(res2.pending_items) == 0
        assert len(res2.items) == 1

        # Completed assessment and active selection now durable
        asmt_saved = engine.assessments.get_latest_assessment(can_id)
        assert asmt_saved is not None
        assert asmt_saved.assessment_id == asmt_success.assessment_id
        assert asmt_saved.final_disposition == AssessmentDisposition.ELIGIBLE

        sel_saved = engine.pipeline_work.get_active_selection(can_id)
        assert sel_saved is not None
        assert sel_saved.assessment_id == asmt_success.assessment_id
