"""Integration tests for LLM assessment mode and MATCH-02 integration (RUN-01-S09)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
    AssessmentRunResult,
)
from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.assessment.service import AssessmentService
from job_automation.configuration import AppConfig
from job_automation.context.selector import ContextSelectorV2Service
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
    FindingStatus,
    HardCriterionResult,
    PostingAvailability,
    RequirementCategory,
    RequirementObligation,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.errors import MissingComponentError
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import (
    AssessmentMode,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.selection import SelectionManager
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot
from tests.fakes.model_transport import ScriptedModelTransport


class TestLLMPipelineIntegration:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "llm_data" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
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

    def test_llm_mode_missing_component_exits_code_2(
        self,
        tmp_path: Path,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """When LLM mode is requested but MATCH-02 component cannot be loaded, exit code 2."""
        data_root = tmp_path / "llm_data"
        runner = PipelineRunner(data_root=data_root, engine=engine)

        with patch("job_automation.orchestration.runner.build_llm_assessor") as mock_build:
            mock_build.side_effect = MissingComponentError("MATCH-02 service unavailable")
            opts = RunOptions(
                assessment_mode="llm",
                enable_sync=False,
            )
            report = runner.start_run(
                options=opts,
                profile_override=candidate_profile,
                policy_override=passing_policy,
                effective_sources_override=[],
            )

            assert report.exit_code == 2
            assert report.c15_summary.status == RunStatus.FAILED
            assert any(e.category == ErrorCategory.MISSING_CONFIGURATION for e in report.c15_summary.errors)

    def test_deterministic_rejection_precedence_bypasses_llm(
        self,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
    ) -> None:
        """Deterministic confirmed hard failures remain REJECTED without calling the LLM."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att)

        req = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="cfg_hash",
        )

        strict_policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[
                HardCriterion(
                    criterion_id="hard_0",
                    name="No Junior roles",
                    field="title",
                    operator="not_contains",
                    expected_value="Junior",
                )
            ],
        )

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p101")
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p101",
            raw_reference="raw/p101.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="Acme Corp",
            title="Junior Software Engineer",
            description_clean="Entry level junior role.",
            observed_at=now,
        )
        binding = PostingBinding(
            canonical_job_id=can_id,
            revision_id=uuid.uuid4(),
            normalized_content_hash=f"sha256:{'a'*64}",
            raw_reference="raw/p101.json",
            raw_content_hash=f"sha256:{'1'*64}",
            source_key=sk,
            c06_snapshot=c06,
        )
        engine.pipeline_work.save_posting_binding(binding)

        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=binding.revision_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        mock_llm = MagicMock()
        coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm,
        )

        res = coord.execute_assessment(
            request=req,
            attempt=att,
            bindings=[binding],
            profile=candidate_profile,
            policy=strict_policy,
        )

        assert res.rejected_count == 1
        assert res.eligible_count == 0
        assert res.total_evaluated == 1
        # Precedence 1: Hard failure remains rejected; model was NEVER invoked
        assert mock_llm.assess.call_count == 0
        assert res.model_invocations_count == 0

        # Verify persisted assessment in database
        asmt = engine.assessments.get_latest_assessment(can_id)
        assert asmt is not None
        assert asmt.final_disposition == AssessmentDisposition.REJECTED
        assert asmt.assessment_method == AssessmentMethod.RULES

    def test_llm_mode_evaluates_passing_candidate_with_scripted_model(
        self,
        tmp_path: Path,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """Passing deterministic rules invoke LLM via AssessorV2 and record output."""
        data_root = tmp_path / "llm_data"
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att)

        req = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="cfg_hash",
        )

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p202")
        content_hash = f"sha256:{'b'*64}"
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p202",
            raw_reference="raw/p202.json",
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
            raw_reference="raw/p202.json",
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

        # Set up real ScriptedModelTransport + LocalModelProvider + LLMAssessmentService
        transport = ScriptedModelTransport()
        app_cfg = AppConfig(
            data_root=str(data_root),
            model_service_url="http://127.0.0.1:11434",
        )
        resolver = InMemoryInputResolver()
        recorder = InMemoryAuditRecorder()
        model_provider = LocalModelProvider.from_config(
            config=app_cfg,
            input_resolver=resolver,
            audit_recorder=recorder,
            transport=transport,
        )
        context_selector = ContextSelectorV2Service(index_store=None, model_provider=None)
        llm_service = LLMAssessmentService(
            context_selector=context_selector,
            model_provider=model_provider,
            input_resolver=resolver,
        )

        # Script the LLM response
        fact1 = candidate_profile.evidence_records[0]
        model_proposal = {
            "findings": [
                {
                    "requirement_id": "req_0",
                    "status": "match",
                    "reason": "Expert Python programmer matches senior role",
                    "score": 95.0,
                    "candidate_evidence": [
                        {
                            "source_kind": "candidate",
                            "profile_version": candidate_profile.profile_version,
                            "fact_id": str(fact1.fact_id),
                        }
                    ],
                },
                {
                    "requirement_id": "req_1",
                    "status": "match",
                    "reason": "Cloud architecture experience demonstrated",
                    "score": 90.0,
                    "candidate_evidence": [
                        {
                            "source_kind": "candidate",
                            "profile_version": candidate_profile.profile_version,
                            "fact_id": str(fact1.fact_id),
                        }
                    ],
                },
            ],
            "relevance_score": 95.0,
            "score_scale": "0-100",
            "summary_reason": "High relevance match for senior Python engineer.",
        }
        transport.queue_response(
            "/api/generate",
            200,
            body={
                "response": json.dumps(model_proposal),
                "done": True,
                "done_reason": "stop",
                "total_duration": 150000000,
                "prompt_eval_count": 150,
                "eval_count": 80,
            },
        )

        coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=llm_service,
        )

        res = coord.execute_assessment(
            request=req,
            attempt=att,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
        )

        assert res.eligible_count == 1
        assert res.rejected_count == 0
        assert res.total_evaluated == 1
        assert res.model_invocations_count == 1
        assert len(res.items) == 1

        # Verify assessment was saved to DB and selection registered
        asmt = engine.assessments.get_latest_assessment(can_id)
        assert asmt is not None
        assert asmt.final_disposition == AssessmentDisposition.ELIGIBLE
        assert asmt.assessment_method == AssessmentMethod.LLM
        assert asmt.relevance_score == 95.0
        assert asmt.model_metadata is not None
        assert asmt.model_metadata.context_strategy == ContextStrategy.JSON

        sel = engine.pipeline_work.get_active_selection(can_id)
        assert sel is not None
        assert sel.assessment_id == asmt.assessment_id

    def test_llm_mode_json_and_rag_strategy_dispatch(
        self,
        tmp_path: Path,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        passing_policy: SearchPolicy,
    ) -> None:
        """Verify context strategy dispatch preserves explicit strategy between JSON and RAG."""
        now = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att)

        can_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p303")
        content_hash = f"sha256:{'3'*64}"
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p303",
            raw_reference="raw/p303.json",
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
            raw_reference="raw/p303.json",
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

        captured_requests = []
        mock_llm = MagicMock()

        def fake_assess(req):
            captured_requests.append(req)
            asmt = Assessment(
                assessment_id=uuid.uuid4(),
                canonical_job_id=req.canonical_job_id,
                posting_revision=req.posting_revision,
                profile_version=req.profile.profile_version,
                policy_version=req.policy.policy_version,
                assessment_method=AssessmentMethod.LLM,
                rule_outcomes=[],
                requirement_findings=[],
                relevance_decision=AssessmentDisposition.ELIGIBLE,
                relevance_score=88.0,
                score_scale="0-100",
                summary_reason="RAG match verified",
                final_disposition=AssessmentDisposition.ELIGIBLE,
                model_metadata=LLMAssessmentMetadata(
                    model_identifier="llama3:8b",
                    prompt_version="v1",
                    context_strategy=ContextStrategy.RAG,
                ),
            )
            return AssessmentRunResult(
                status="success",
                assessment=asmt,
                input_fingerprint="fp123",
            )

        mock_llm.assess.side_effect = fake_assess

        coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=mock_llm,
        )

        req_rag = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.LLM,
            primary_strategy=ContextStrategy.RAG,
            app_config_hash="cfg_hash",
        )

        res = coord.execute_assessment(
            request=req_rag,
            attempt=att,
            bindings=[binding],
            profile=candidate_profile,
            policy=passing_policy,
        )

        assert res.eligible_count == 1
        assert len(captured_requests) == 1
        # Explicit RAG strategy passed down to LLM request
        assert captured_requests[0].context_strategy == ContextStrategy.RAG

