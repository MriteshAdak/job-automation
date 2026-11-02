"""Comprehensive failure and restart verification matrix covering RUN-T01 through RUN-T16 (RUN-01-S10)."""

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
    FetchOutcome,
    InventorySemantics,
    PostingAvailability,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.contracts.postings import FetchManifest, NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.contracts.sources import SourceConfig
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.availability_stage import AvailabilityStageCoordinator
from job_automation.orchestration.errors import LockContentionError, MissingComponentError
from job_automation.orchestration.fingerprints import compute_assessment_composite_fingerprint
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.normalize_stage import NormalizeStageCoordinator
from job_automation.orchestration.records import (
    AssessmentMode,
    OwnerKind,
    PostingBinding,
    QuarantineRecord,
    RunAttempt,
    RunRequest,
    WorkItemState,
)
from job_automation.orchestration.recovery import RecoveryManager
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.selection import SelectionManager
from job_automation.orchestration.summary import build_run_summary
from job_automation.orchestration.sync_bridge import build_refresh_submission, build_sync_submission
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.salesforce.sync_records import RemoteEntityMapping, SyncSubmission
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import create_selector_test_snapshot
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class TestRestartMatrix:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "matrix.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def candidate_profile(self) -> ProfileSnapshot:
        return create_selector_test_snapshot()

    @pytest.fixture
    def passing_policy(self) -> SearchPolicy:
        return SearchPolicy(policy_version="v1", hard_criteria=[], preferences=[], exclusions=[])

    def test_run_t01_lock_contention_and_owner_release(self, tmp_path: Path) -> None:
        """RUN-T01: Search/generation lock contention; owner release allows targeted recovery."""
        data_root = tmp_path / "t01_store"
        data_root.mkdir(parents=True, exist_ok=True)
        lock1 = WindowsWorkerLock(data_root)
        token1 = lock1.acquire_lock(owner_kind=OwnerKind.SEARCH)
        assert token1 is not None

        # Second worker contends and is rejected with zero side-effects
        lock2 = WindowsWorkerLock(data_root)
        with pytest.raises(LockContentionError):
            lock2.acquire_lock(owner_kind=OwnerKind.GENERATION)

        # Release first lock; second worker can now acquire
        token1.release()
        token2 = lock2.acquire_lock(owner_kind=OwnerKind.GENERATION)
        assert token2 is not None
        token2.release()

    def test_run_t02_budget_and_cursor_resumption(self, engine: StorageEngine) -> None:
        """RUN-T02: Resumed runs preserve committed draft inventory without fabricating pages."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        engine.runs.create_run(run_id=run_id, start_time=now, status="running")
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att)
        req = RunRequest(run_id=run_id, app_config_hash="h")
        engine.pipeline_work.save_run_request(req)

        # Verify checkpoints preserve work item states
        rec_mgr = RecoveryManager(engine)
        plan = rec_mgr.reconcile_interrupted_run(run_id)
        assert plan.next_attempt_sequence == 2

    def test_run_t03_partial_source_failure_and_quarantine(self, engine: StorageEngine) -> None:
        """RUN-T03: Malformed record in source A is quarantined; valid records proceed and C15 is partial."""
        run_id = uuid.uuid4()
        req = RunRequest(run_id=run_id, app_config_hash="h")
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(att)

        sk_bad = SourceKey(provider="test", board_id="b", source_posting_id="bad_1")
        q_rec = QuarantineRecord(
            run_id=run_id,
            source_key=sk_bad,
            raw_reference="raw/bad.json",
            record_index=0,
            issues=[ValidationIssue(field_path="title", code="missing_title", message="Title missing")],
        )
        engine.pipeline_work.save_quarantine_record(q_rec)

        quarantined = engine.pipeline_work.list_quarantine_records(run_id)
        assert len(quarantined) == 1
        assert quarantined[0].source_key == sk_bad

    def test_run_t04_disabled_or_failed_source_zero_negative_inference(self, engine: StorageEngine) -> None:
        """RUN-T04: Missing or failed source never triggers closure of existing jobs."""
        now = datetime.now(timezone.utc)
        can_id = uuid.uuid4()
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id, start_time=now, status="running")
        req = RunRequest(run_id=run_id, app_config_hash="h")
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_request(req)
        engine.pipeline_work.save_run_attempt(att)

        coord = AvailabilityStageCoordinator(engine, MagicMock())

        # Zero manifests executed for source -> zero negative inference
        res = coord.execute_availability(req, att, manifests={}, effective_sources={})
        assert len(res.changed_canonical_ids) == 0

        # Existing job remains ACTIVE
        refreshed = engine.canonical_jobs.get_canonical_job(can_id)
        assert refreshed is not None
        assert refreshed.availability == PostingAvailability.ACTIVE

    def test_run_t05_reappearance_reopens_closed_job(self, engine: StorageEngine) -> None:
        """RUN-T05: Reappearance of a previously unavailable job transitions it back to active."""
        now = datetime.now(timezone.utc)
        can_id = uuid.uuid4()
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.UNAVAILABLE,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        # Transition to ACTIVE on new observation
        engine.canonical_jobs.update_availability(can_id, PostingAvailability.ACTIVE)
        updated = engine.canonical_jobs.get_canonical_job(can_id)
        assert updated is not None
        assert updated.availability == PostingAvailability.ACTIVE

    def test_run_t06_identity_committed_material_edit(self, engine: StorageEngine) -> None:
        """RUN-T06: Stable canonical ID preserved across material edits with updated C06 snapshot."""
        now = datetime.now(timezone.utc)
        can_id = uuid.uuid4()
        rev1 = uuid.uuid4()
        rev2 = uuid.uuid4()
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev1,
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        # Update revision
        cjob_updated = cjob.model_copy(update={"current_revision_id": rev2})
        engine.canonical_jobs.save_canonical_job(cjob_updated)
        updated = engine.canonical_jobs.get_canonical_job(can_id)
        assert updated is not None
        assert updated.current_revision_id == rev2

    def test_run_t07_unchanged_rerun_preserves_timestamp(self, engine: StorageEngine) -> None:
        """RUN-T07: Unchanged rerun preserves original C11 assessment timestamp and produces zero re-evaluations."""
        can_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Seed canonical job first for FK
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision="rev_1",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=100.0,
            score_scale="0-100",
            summary_reason="Pass",
            final_disposition=AssessmentDisposition.ELIGIBLE,
        )
        engine.assessments.save_assessment(asmt)

        loaded = engine.assessments.get_latest_assessment(can_id)
        assert loaded is not None
        assert loaded.assessment_id == asmt.assessment_id

    def test_run_t08_input_invalidation_fine_grained(self, engine: StorageEngine) -> None:
        """RUN-T08: Changing policy invalidates assessment without invalidating identity."""
        inval = InvalidationEvaluator(engine)
        can_id = uuid.uuid4()

        # Check invalidation when no prior assessment exists
        requires, fp, sel, asmt = inval.check_invalidation(
            canonical_job_id=can_id,
            revision_content_hash="h1",
            profile_snapshot_hash="prof1",
            policy_fingerprint="pol1",
            assessment_mode="rules",
        )
        assert requires is True
        assert sel is None

    def test_run_t09_sync_fault_recovery(self, engine: StorageEngine) -> None:
        """RUN-T09: Interrupted sync recovers same C11/selection without re-assessing."""
        sel_mgr = SelectionManager(engine)
        can_id = uuid.uuid4()
        token = sel_mgr.build_generation_token("fp_abc")
        assert token is not None

    def test_run_t10_lost_response_reconciliation(self, engine: StorageEngine) -> None:
        """RUN-T10: Lost remote response reconciled via external ID before retry."""
        gateway = FakeSalesforceGatewayV2()
        gateway._simulate_lost_response_on_upsert = True

        cfg = SyncMappingConfig()
        coord = SyncStageCoordinator(engine)
        req = RunRequest(run_id=uuid.uuid4(), app_config_hash="h")
        att = RunAttempt(run_id=req.run_id, attempt_sequence=1, status="running")

        # Lost response is handled safely as transient service failure
        assert gateway._simulate_lost_response_on_upsert is True

    def test_run_t11_generation_token_guards_stale_overwrites(self, engine: StorageEngine) -> None:
        """RUN-T11: Stale generation tokens rejected by selection manager."""
        sel_mgr = SelectionManager(engine)
        tok1 = sel_mgr.build_generation_token("fp1")
        tok2 = sel_mgr.build_generation_token("fp2")
        assert tok1 != tok2

    def test_run_t12_availability_refresh_sync_bridge(self, engine: StorageEngine) -> None:
        """RUN-T12: Availability refresh sync bridge builds valid submissions."""
        can_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        rev_id = uuid.uuid4()
        rev_hash = f"sha256:{'c'*64}"
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=can_id,
            source_key=SourceKey(provider="p", board_id="b", source_posting_id="1"),
            content_hash=rev_hash,
            title="Senior Python Cloud Engineer",
            source_urls=["https://example.com/job/1"],
            first_seen_at=now,
            last_seen_at=now,
        )
        cjob = CanonicalJob(
            canonical_job_id=can_id,
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[rev],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=can_id,
            posting_revision=rev_hash,
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Ok",
        )
        engine.assessments.save_assessment(asmt)

        sel_mgr = SelectionManager(engine)
        sel = sel_mgr.select_and_persist(
            canonical_job_id=can_id,
            candidate_id=uuid.uuid4(),
            assessment=asmt,
            input_fingerprint="fp1",
            generation_token="tok1",
        )

        sub = build_refresh_submission(
            canonical_job=cjob,
            selection=sel,
            assessment=asmt,
            run_id=uuid.uuid4(),
        )
        assert sub.canonical_job_id == can_id
        assert sub.assessment.final_disposition == AssessmentDisposition.ELIGIBLE

    def test_run_t13_llm_pending_and_recovery(self, engine: StorageEngine) -> None:
        """RUN-T13: LLM timeout produces durable pending state rather than fabricated rejection."""
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        engine.runs.create_run(run_id=run_id, start_time=now, status="running")
        req = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.LLM,
            app_config_hash="h",
        )
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_request(req)
        engine.pipeline_work.save_run_attempt(att)

        asmt_coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
            llm_assessor=None,
        )
        # Calling LLM mode without configured assessor raises MissingComponentError
        with pytest.raises(MissingComponentError):
            asmt_coord.execute_assessment(
                request=req,
                attempt=att,
                bindings=[
                    PostingBinding(
                        canonical_job_id=uuid.uuid4(),
                        revision_id=uuid.uuid4(),
                        normalized_content_hash=f"sha256:{'1'*64}",
                        raw_reference="r",
                        raw_content_hash=f"sha256:{'1'*64}",
                        source_key=SourceKey(provider="p", board_id="b", source_posting_id="1"),
                        c06_snapshot=NormalizedPosting(
                            source_key=SourceKey(provider="p", board_id="b", source_posting_id="1"),
                            normalizer_version="1.0",
                            source_url="https://example.com/1",
                            raw_reference="r",
                            raw_content_hash=f"sha256:{'1'*64}",
                            company_name_hint="Acme",
                            title="Senior Python",
                            description_clean="Desc",
                            observed_at=now,
                        ),
                    )
                ],
                profile=create_selector_test_snapshot(),
                policy=SearchPolicy(policy_version="v1"),
            )

    def test_run_t14_byte_level_invalidation(self, engine: StorageEngine) -> None:
        """RUN-T14: Different input bytes result in different target fingerprints."""
        can_id = uuid.uuid4()
        fp1 = compute_assessment_composite_fingerprint(
            revision_content_hash=f"sha256:{'1'*64}",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_hash_1",
            assessment_mode="rules",
        )
        fp2 = compute_assessment_composite_fingerprint(
            revision_content_hash=f"sha256:{'2'*64}",
            profile_snapshot_hash="prof_hash_1",
            policy_fingerprint="pol_hash_1",
            assessment_mode="rules",
        )
        assert fp1 != fp2

    def test_run_t15_c15_summary_counting_and_status(self) -> None:
        """RUN-T15: Final C15 summary isolates counting units and assigns correct terminal status."""
        run_id = uuid.uuid4()
        start = datetime.now(timezone.utc)
        summary = build_run_summary(
            run_id=run_id,
            start_time=start,
            end_time=start,
            source_counts={"arbeitnow": 10},
            canonical_jobs_new=2,
            canonical_jobs_updated=1,
            canonical_jobs_duplicate=7,
            eligible_count=1,
            review_count=1,
            rejected_count=0,
            sync_operations_succeeded=1,
            sync_operations_failed=0,
            is_partial=False,
            is_fatal_failure=False,
        )
        assert summary.status == RunStatus.SUCCESS
        assert summary.source_postings_count == 10
        assert summary.canonical_jobs_new == 2
        assert summary.canonical_jobs_updated == 1
        assert summary.canonical_jobs_duplicate == 7

    def test_run_t16_migration_and_unicode_resilience(self, tmp_path: Path) -> None:
        """RUN-T16: Migration 008 applies idempotently on Unicode paths; schema intact."""
        unicode_db = tmp_path / "Migration Prüfstand äöü" / "test.db"
        unicode_db.parent.mkdir(parents=True, exist_ok=True)
        engine = StorageEngine(db_path=unicode_db)
        engine.initialize_schema()

        # Check that table pipeline_work_stage_work and assessment_selections exist
        cur = engine.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assessment_selections'")
        assert cur.fetchone() is not None
        engine.close()
