"""Tests for LLM assessment invalidation matrix and zero-model-call reuse (RUN-01-S06, S09)."""

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
)
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
)
from job_automation.orchestration.selection import SelectionManager
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot


class TestLLMInvalidation:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "llm_inval.db"
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

    def test_unchanged_llm_rerun_performs_zero_model_calls(
        self,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """Unchanged LLM rerun reuses existing C11 assessment, performing 0 model calls."""
        now = datetime.now(timezone.utc)
        run_id1 = uuid.uuid4()
        engine.runs.create_run(run_id=run_id1)
        att1 = RunAttempt(run_id=run_id1, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att1)

        req1 = RunRequest(
            run_id=run_id1,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="cfg_hash",
        )

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p505")
        content_hash = f"sha256:{'5'*64}"
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p505",
            raw_reference="raw/p505.json",
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
            raw_reference="raw/p505.json",
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

        mock_llm = MagicMock()
        asmt1 = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision=content_hash,
            profile_version=candidate_profile.profile_version,
            policy_version=passing_policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=[],
            requirement_findings=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=94.0,
            score_scale="0-100",
            summary_reason="Initial LLM evaluation",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=LLMAssessmentMetadata(
                model_identifier="llama3:8b-instruct-q4_K_M",
                prompt_version="v1",
                context_strategy=ContextStrategy.JSON,
            ),
        )
        mock_llm.assess.return_value = AssessmentRunResult(
            status="success",
            assessment=asmt1,
            input_fingerprint="fp1",
        )

        coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm,
        )

        # -------------------------------------------------------------
        # Run 1: Evaluates job with 1 model call
        # -------------------------------------------------------------
        res1 = coord.execute_assessment(
            request=req1,
            attempt=att1,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
        )
        assert res1.eligible_count == 1
        assert res1.reused_count == 0
        assert res1.model_invocations_count == 1
        assert mock_llm.assess.call_count == 1

        # -------------------------------------------------------------
        # Run 2: Unchanged rerun on a new run ID
        # -------------------------------------------------------------
        run_id2 = uuid.uuid4()
        engine.runs.create_run(run_id=run_id2)
        att2 = RunAttempt(run_id=run_id2, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att2)

        req2 = RunRequest(
            run_id=run_id2,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="cfg_hash",
        )

        res2 = coord.execute_assessment(
            request=req2,
            attempt=att2,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="v1",
        )

        # Zero new evaluations! Reused counter incremented
        assert res2.reused_count == 1
        assert res2.eligible_count == 0
        assert res2.total_evaluated == 0
        # Critical verification: LLM was NOT called on rerun!
        assert res2.model_invocations_count == 0
        assert mock_llm.assess.call_count == 1  # Still 1 from Run 1

        # Assessment ID and selected result remain identical
        assert res2.items[0].assessment.assessment_id == asmt1.assessment_id
        assert res2.items[0].is_reused is True

    def test_changing_model_or_prompt_invalidates_and_invokes_llm(
        self,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """Changing model identifier or prompt version invalidates C11 and triggers new model assessment."""
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
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p606")
        content_hash = f"sha256:{'6'*64}"
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p606",
            raw_reference="raw/p606.json",
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
            raw_reference="raw/p606.json",
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

        mock_llm = MagicMock()
        asmt_v1 = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision=content_hash,
            profile_version=candidate_profile.profile_version,
            policy_version=passing_policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=[],
            requirement_findings=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=90.0,
            score_scale="0-100",
            summary_reason="v1 prompt output",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=LLMAssessmentMetadata(
                model_identifier="llama3:8b",
                prompt_version="v1",
                context_strategy=ContextStrategy.JSON,
            ),
        )
        asmt_v2 = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision=content_hash,
            profile_version=candidate_profile.profile_version,
            policy_version=passing_policy.policy_version,
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=[],
            requirement_findings=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=95.0,
            score_scale="0-100",
            summary_reason="v2 prompt output",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=LLMAssessmentMetadata(
                model_identifier="llama3:8b",
                prompt_version="v2",
                context_strategy=ContextStrategy.JSON,
            ),
        )
        mock_llm.assess.side_effect = [
            AssessmentRunResult(status="success", assessment=asmt_v1, input_fingerprint="fp_v1"),
            AssessmentRunResult(status="success", assessment=asmt_v2, input_fingerprint="fp_v2"),
        ]

        coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm,
        )

        # 1. Initial run with prompt v1
        res1 = coord.execute_assessment(
            request=req,
            attempt=att1,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
            model_identifier="llama3:8b",
            prompt_version="v1",
        )
        assert res1.eligible_count == 1
        assert res1.model_invocations_count == 1
        assert mock_llm.assess.call_count == 1

        # 2. Upgrade prompt to v2 -> must invalidate and re-run LLM
        att2 = RunAttempt(run_id=run_id, attempt_sequence=2, status="running")
        res2 = coord.execute_assessment(
            request=req,
            attempt=att2,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
            model_identifier="llama3:8b",
            prompt_version="v2",
        )
        assert res2.eligible_count == 1
        assert res2.reused_count == 0
        assert res2.model_invocations_count == 1
        assert mock_llm.assess.call_count == 2
        assert res2.items[0].assessment.assessment_id == asmt_v2.assessment_id

