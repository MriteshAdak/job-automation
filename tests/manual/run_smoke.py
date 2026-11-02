"""Manual smoke verification script for RUN-01 pipeline execution and recovery.

Supports three verification scenarios:
  1. deterministic-rerun: Executes a full deterministic rules run followed by an unchanged
     rerun, asserting zero duplicate remote writes, zero re-evaluations, and timestamp retention.
  2. crash-recovery: Simulates an interrupted attempt, reconciles via RecoveryManager, resumes
     via PipelineRunner.resume_run(), and validates attempt sequence increment and state preservation.
  3. llm-json-rag: Validates MATCH-02 model assessment across JSON and RAG strategies with scripted
     transports, verifying zero-model-call reuse on unchanged reruns and proper invalidation on strategy switch.

Usage:
  python tests/manual/run_smoke.py --data-root <path> --scenario deterministic-rerun
  python tests/manual/run_smoke.py --data-root <path> --scenario crash-recovery
  python tests/manual/run_smoke.py --data-root <path> --scenario llm-json-rag
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_automation.assessment.llm_records import AssessmentRunResult
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
from job_automation.contracts.sources import SourceConfig
from job_automation.models.audit import InMemoryAuditRecorder
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.provider import LocalModelProvider
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import (
    AssessmentMode,
    PostingBinding,
    RunAttempt,
    RunRequest,
    WorkItemState,
)
from job_automation.orchestration.recovery import RecoveryManager
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.selection import SelectionManager
from job_automation.orchestration.sync_bridge import build_sync_submission
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.salesforce.sync_records import SyncSubmission
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider
from tests.fakes.model_transport import ScriptedModelTransport
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_smoke")


def build_candidate_profile() -> ProfileSnapshot:
    """Build an approved candidate profile snapshot."""
    return create_selector_test_snapshot()


def build_passing_policy() -> SearchPolicy:
    """Build a search policy with no hard exclusions."""
    return SearchPolicy(
        policy_version="v1",
        hard_criteria=[],
        preferences=[],
        exclusions=[],
    )


def run_deterministic_rerun(data_root: Path) -> int:
    """Verify deterministic pipeline execution, unchanged rerun, and Salesforce sync."""
    logger.info("=== Running Scenario: deterministic-rerun ===")
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "job_automation.db"
    raw_dir = data_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    engine.initialize_schema()

    gateway = FakeSalesforceGatewayV2()
    now = datetime.now(timezone.utc)
    cand_profile = build_candidate_profile()
    policy = build_passing_policy()

    # Seed 1 synthetic job posting
    can_id = uuid.uuid4()
    sk = SourceKey(provider="smoke", board_id="berlin", source_posting_id="smoke-job-1")
    content_hash = f"sha256:{'1'*64}"
    c06 = NormalizedPosting(
        source_key=sk,
        normalizer_version="1.0",
        source_url="https://example.com/smoke/1",
        raw_reference="raw/smoke_1.json",
        raw_content_hash=content_hash,
        company_name_hint="Acme Cloud Solutions",
        title="Senior Python Cloud Engineer",
        description_clean="Expert Python engineer with AWS, PostgreSQL, and distributed systems experience.",
        observed_at=now,
    )
    binding = PostingBinding(
        canonical_job_id=can_id,
        revision_id=uuid.uuid4(),
        normalized_content_hash=content_hash,
        raw_reference="raw/smoke_1.json",
        raw_content_hash=content_hash,
        source_key=sk,
        c06_snapshot=c06,
    )
    engine.pipeline_work.save_posting_binding(binding)

    cjob = CanonicalJob(
        canonical_job_id=can_id,
        company_name="Acme Cloud Solutions",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=binding.revision_id,
        first_seen_at=now,
        last_seen_at=now,
    )
    engine.canonical_jobs.save_canonical_job(cjob)

    # -----------------------------------------------------------------
    # Step 1: Initial Run
    # -----------------------------------------------------------------
    logger.info("Executing Run 1 (Initial deterministic run)...")
    runner = PipelineRunner(data_root=data_root, engine=engine)
    opts1 = RunOptions(
        assessment_mode="rules",
        enable_sync=True,
        run_candidate_backup=True,
        gateway=gateway,
    )

    report1 = runner.start_run(
        options=opts1,
        profile_override=cand_profile,
        policy_override=policy,
        effective_sources_override=[],
    )

    # In our test slice, we manually evaluate the binding through the stage coordinator to test complete DB wiring
    asmt_coord = AssessmentStageCoordinator(
        engine=engine,
        assessment_service=AssessmentService(),
        selection_manager=SelectionManager(engine),
        invalidation_evaluator=InvalidationEvaluator(engine),
    )
    req1 = engine.pipeline_work.get_run_request(report1.c15_summary.run_id)
    att1 = engine.pipeline_work.get_latest_attempt(report1.c15_summary.run_id)
    assert req1 is not None and att1 is not None

    asmt_res1 = asmt_coord.execute_assessment(
        request=req1,
        attempt=att1,
        bindings=[binding],
        profile=cand_profile,
        policy=policy,
    )
    assert asmt_res1.eligible_count == 1
    assert asmt_res1.reused_count == 0

    # Sync to gateway
    sync_coord = SyncStageCoordinator(engine)
    sync_sub = build_sync_submission(
        selection=asmt_res1.items[0].selection,
        assessment=asmt_res1.items[0].assessment,
        canonical_job=cjob,
        binding=binding,
        run_id=report1.c15_summary.run_id,
    )
    sync_res1 = sync_coord.execute_sync(
        request=req1,
        attempt=att1,
        submissions=[sync_sub],
        config=SyncMappingConfig(),
        gateway=gateway,
        run_candidate_backup=True,
    )
    assert sync_res1.sync_operations_succeeded == 1

    # Verify SQLite record identities and counts
    asmt1 = engine.assessments.get_latest_assessment(can_id)
    assert asmt1 is not None
    assert asmt1.final_disposition == AssessmentDisposition.ELIGIBLE
    timestamp1 = asmt1.assessment_id

    sel1 = engine.pipeline_work.get_active_selection(can_id)
    assert sel1 is not None
    assert sel1.is_selected_final is True

    # Verify remote record in fake Salesforce gateway
    remote_jobs = list(gateway.records.get("Job__c", {}).values())
    assert len(remote_jobs) == 1
    assert remote_jobs[0]["Name"] == "Senior Python Cloud Engineer"

    # Verify candidate snapshots repository is accessible and sync result succeeded
    assert sync_res1.sync_operations_succeeded == 1
    assert sync_res1.backup_result is not None
    logger.info("Run 1 verified: assessment and Salesforce sync successful.")

    # -----------------------------------------------------------------
    # Step 2: Unchanged Rerun
    # -----------------------------------------------------------------
    logger.info("Executing Run 2 (Unchanged rerun)...")
    run_id2 = uuid.uuid4()
    engine.runs.create_run(run_id=run_id2, start_time=now, status="running")
    req2 = RunRequest(run_id=run_id2, assessment_mode=AssessmentMode.RULES, app_config_hash="cfg_hash")
    att2 = RunAttempt(run_id=run_id2, attempt_sequence=1, status="running")
    engine.pipeline_work.save_run_request(req2)
    engine.pipeline_work.save_run_attempt(att2)

    asmt_res2 = asmt_coord.execute_assessment(
        request=req2,
        attempt=att2,
        bindings=[binding],
        profile=cand_profile,
        policy=policy,
    )

    # Strict C15 assertion: 0 newly evaluated, 1 reused!
    assert asmt_res2.eligible_count == 0
    assert asmt_res2.reused_count == 1
    assert asmt_res2.items[0].is_reused is True
    assert asmt_res2.items[0].assessment.assessment_id == asmt1.assessment_id

    # Verify zero duplicate remote records created
    remote_jobs_after = list(gateway.records.get("Job__c", {}).values())
    assert len(remote_jobs_after) == 1

    engine.close()
    logger.info("Deterministic rerun smoke PASSED cleanly.")
    return 0


def run_crash_recovery(data_root: Path) -> int:
    """Verify lock release, RecoveryManager reconciliation, and resume execution."""
    logger.info("=== Running Scenario: crash-recovery ===")
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "job_automation.db"

    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    engine.runs.create_run(run_id=run_id, start_time=now, status="running")
    req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
    att1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
    engine.pipeline_work.save_run_request(req)
    engine.pipeline_work.save_run_attempt(att1)

    # 1. Simulate process acquiring lock and crashing
    lock = WindowsWorkerLock(data_root)
    token = lock.acquire_lock()
    assert token is not None
    # Token released as if OS cleared handle on process exit
    token.release()

    # 2. Reconcile interrupted attempt
    rec_mgr = RecoveryManager(engine)
    rec_plan = rec_mgr.reconcile_interrupted_run(run_id)

    assert rec_plan.next_attempt_sequence == 2
    assert rec_plan.prior_attempt is not None
    assert rec_plan.prior_attempt.attempt_sequence == 1

    # Verify attempt 1 was marked interrupted in SQLite
    latest_att = engine.pipeline_work.get_latest_attempt(run_id)
    assert latest_att is not None
    assert latest_att.status == "interrupted"

    # 3. Resume the run via PipelineRunner
    cand_profile = build_candidate_profile()
    policy = build_passing_policy()
    runner = PipelineRunner(data_root=data_root, engine=engine)
    opts = RunOptions(assessment_mode="rules", enable_sync=False)

    report = runner.resume_run(
        run_id=run_id,
        options=opts,
        profile_override=cand_profile,
        policy_override=policy,
        effective_sources_override=[],
    )

    assert report.exit_code == 0
    assert report.attempt_sequence == 2
    assert report.c15_summary.status == RunStatus.SUCCESS

    # Verify attempt history in DB
    attempts = engine.pipeline_work.list_attempts(run_id)
    assert len(attempts) == 2
    assert attempts[0].attempt_sequence == 1
    assert attempts[0].status == "interrupted"
    assert attempts[1].attempt_sequence == 2
    assert attempts[1].status == "succeeded"

    engine.close()
    logger.info("Crash recovery smoke PASSED cleanly.")
    return 0


def run_llm_json_rag(data_root: Path) -> int:
    """Verify MATCH-02 LLM assessment, JSON/RAG strategies, and zero-model-call reuse."""
    logger.info("=== Running Scenario: llm-json-rag ===")
    data_root.mkdir(parents=True, exist_ok=True)
    db_path = data_root / "job_automation.db"

    indexes_dir = data_root / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    engine.initialize_schema()

    cand_profile = build_candidate_profile()
    policy = build_passing_policy()
    now = datetime.now(timezone.utc)

    # Build active test index for RAG support
    fake_emb_provider = DeterministicFakeEmbeddingProvider(dimension=8)
    _, index_store, _ = build_and_activate_test_index(
        storage_engine=engine,
        indexes_dir=indexes_dir,
        snapshot=cand_profile,
        purpose="assessment",
        dimension=8,
        provider=fake_emb_provider,
    )

    # Seed job
    can_id = uuid.uuid4()
    sk = SourceKey(provider="smoke", board_id="berlin", source_posting_id="smoke-llm-1")
    content_hash = f"sha256:{'7'*64}"
    c06 = NormalizedPosting(
        source_key=sk,
        normalizer_version="1.0",
        source_url="https://example.com/smoke/llm1",
        raw_reference="raw/smoke_llm1.json",
        raw_content_hash=content_hash,
        company_name_hint="AI Cloud Systems",
        title="Senior Python Backend Developer",
        description_clean="Senior Python developer with cloud and database experience.",
        observed_at=now,
    )
    binding = PostingBinding(
        canonical_job_id=can_id,
        revision_id=uuid.uuid4(),
        normalized_content_hash=content_hash,
        raw_reference="raw/smoke_llm1.json",
        raw_content_hash=content_hash,
        source_key=sk,
        c06_snapshot=c06,
    )
    engine.pipeline_work.save_posting_binding(binding)

    cjob = CanonicalJob(
        canonical_job_id=can_id,
        company_name="AI Cloud Systems",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=binding.revision_id,
        first_seen_at=now,
        last_seen_at=now,
    )
    engine.canonical_jobs.save_canonical_job(cjob)

    # Set up real ScriptedModelTransport + LocalModelProvider + LLMAssessmentService
    transport = ScriptedModelTransport()
    app_cfg = AppConfig(data_root=str(data_root), model_service_url="http://127.0.0.1:11434")
    resolver = InMemoryInputResolver()
    recorder = InMemoryAuditRecorder()
    model_provider = LocalModelProvider.from_config(
        config=app_cfg,
        input_resolver=resolver,
        audit_recorder=recorder,
        transport=transport,
    )
    context_selector = ContextSelectorV2Service(
        index_store=index_store,
        model_provider=fake_emb_provider,
    )
    llm_service = LLMAssessmentService(
        context_selector=context_selector,
        model_provider=model_provider,
        input_resolver=resolver,
    )

    coord = AssessmentStageCoordinator(
        engine=engine,
        assessment_service=AssessmentService(),
        selection_manager=SelectionManager(engine),
        invalidation_evaluator=InvalidationEvaluator(engine),
        llm_assessor=llm_service,
    )

    # -----------------------------------------------------------------
    # Phase 1: JSON Strategy Evaluation
    # -----------------------------------------------------------------
    logger.info("Phase 1: Evaluating with JSON strategy...")
    fact1 = cand_profile.evidence_records[0]
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
                        "profile_version": cand_profile.profile_version,
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
                        "profile_version": cand_profile.profile_version,
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

    run_id1 = uuid.uuid4()
    engine.runs.create_run(run_id=run_id1, start_time=now, status="running")
    req1 = RunRequest(
        run_id=run_id1,
        assessment_mode=AssessmentMode.LLM,
        primary_strategy=ContextStrategy.JSON,
        app_config_hash="cfg_hash",
    )
    att1 = RunAttempt(run_id=run_id1, attempt_sequence=1, status="running")
    engine.pipeline_work.save_run_request(req1)
    engine.pipeline_work.save_run_attempt(att1)

    res1 = coord.execute_assessment(
        request=req1,
        attempt=att1,
        bindings=[binding],
        profile=cand_profile,
        policy=policy,
    )

    assert res1.eligible_count == 1
    assert res1.model_invocations_count == 1
    asmt1 = engine.assessments.get_latest_assessment(can_id)
    assert asmt1 is not None
    assert asmt1.assessment_method == AssessmentMethod.LLM
    assert asmt1.model_metadata is not None
    assert asmt1.model_metadata.context_strategy == ContextStrategy.JSON

    # -----------------------------------------------------------------
    # Phase 2: Unchanged Rerun (0 model calls)
    # -----------------------------------------------------------------
    logger.info("Phase 2: Verifying unchanged rerun (0 model calls)...")
    run_id2 = uuid.uuid4()
    engine.runs.create_run(run_id=run_id2, start_time=now, status="running")
    req2 = RunRequest(
        run_id=run_id2,
        assessment_mode=AssessmentMode.LLM,
        primary_strategy=ContextStrategy.JSON,
        app_config_hash="cfg_hash",
    )
    att2 = RunAttempt(run_id=run_id2, attempt_sequence=1, status="running")
    engine.pipeline_work.save_run_request(req2)
    engine.pipeline_work.save_run_attempt(att2)

    res2 = coord.execute_assessment(
        request=req2,
        attempt=att2,
        bindings=[binding],
        profile=cand_profile,
        policy=policy,
    )

    assert res2.reused_count == 1
    assert res2.eligible_count == 0
    assert res2.model_invocations_count == 0

    # -----------------------------------------------------------------
    # Phase 3: Strategy Switch to RAG (triggers invalidation)
    # -----------------------------------------------------------------
    logger.info("Phase 3: Switching strategy to RAG (triggers invalidation)...")
    transport.queue_response(
        "/api/generate",
        200,
        body={
            "response": json.dumps(model_proposal),
            "done": True,
            "done_reason": "stop",
            "total_duration": 160000000,
            "prompt_eval_count": 160,
            "eval_count": 85,
        },
    )

    run_id3 = uuid.uuid4()
    engine.runs.create_run(run_id=run_id3, start_time=now, status="running")
    req3 = RunRequest(
        run_id=run_id3,
        assessment_mode=AssessmentMode.LLM,
        primary_strategy=ContextStrategy.RAG,
        app_config_hash="cfg_hash",
    )
    att3 = RunAttempt(run_id=run_id3, attempt_sequence=1, status="running")
    engine.pipeline_work.save_run_request(req3)
    engine.pipeline_work.save_run_attempt(att3)

    res3 = coord.execute_assessment(
        request=req3,
        attempt=att3,
        bindings=[binding],
        profile=cand_profile,
        policy=policy,
    )

    assert res3.eligible_count == 1
    assert res3.reused_count == 0
    assert res3.model_invocations_count == 1

    asmt3 = engine.assessments.get_latest_assessment(can_id)
    assert asmt3 is not None
    assert asmt3.model_metadata is not None
    assert asmt3.model_metadata.context_strategy == ContextStrategy.RAG

    engine.close()
    logger.info("LLM JSON and RAG smoke PASSED cleanly.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RUN-01 smoke verification harness")
    parser.add_argument("--data-root", type=Path, required=True, help="Data directory root path")
    parser.add_argument(
        "--scenario",
        type=str,
        required=True,
        choices=["deterministic-rerun", "crash-recovery", "llm-json-rag"],
        help="Verification scenario to execute",
    )
    args = parser.parse_args()

    if args.scenario == "deterministic-rerun":
        return run_deterministic_rerun(args.data_root)
    elif args.scenario == "crash-recovery":
        return run_crash_recovery(args.data_root)
    elif args.scenario == "llm-json-rag":
        return run_llm_json_rag(args.data_root)
    else:
        logger.error("Unknown scenario: %s", args.scenario)
        return 1


if __name__ == "__main__":
    sys.exit(main())
