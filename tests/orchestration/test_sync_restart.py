"""Tests for sync stage crash recovery, reconciliation barriers, and stale write prevention (RUN-01-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.salesforce import GatewayFailure, RemoteOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.orchestration.records import (
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.orchestration.sync_bridge import build_sync_submission
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.salesforce.sync_errors import StaleSelectionError
from job_automation.salesforce.sync_records import (
    PublicationDecision,
    SyncStepState,
)
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "sync.example.json"


class TestSyncRestart:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_restart_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    @pytest.fixture
    def gateway(self) -> FakeSalesforceGatewayV2:
        return FakeSalesforceGatewayV2()

    def _seed_canonical_job(
        self,
        engine: StorageEngine,
        job_id: uuid.UUID,
        company_id: uuid.UUID,
        company_name: str = "Resilience Corp",
        title: str = "Distributed Systems Engineer",
    ) -> tuple[CanonicalJob, PostingBinding]:
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")
        rev_id = uuid.uuid4()
        rev_hash = f"sha256:{'b'*64}"
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=job_id,
            source_key=sk,
            content_hash=rev_hash,
            title=title,
            first_seen_at=now,
            last_seen_at=now,
            source_urls=["https://example.com/job/1"],
            availability=PostingAvailability.ACTIVE,
        )
        cjob = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name=company_name,
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[rev],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/job/1",
            raw_reference="raw/p1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint=company_name,
            title=title,
            description_clean="Job desc",
            observed_at=now,
        )
        binding = PostingBinding(
            canonical_job_id=job_id,
            revision_id=rev_id,
            normalized_content_hash=rev_hash,
            raw_reference="raw/p1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            source_key=sk,
            c06_snapshot=c06,
        )
        engine.pipeline_work.save_posting_binding(binding)
        return cjob, binding

    def test_interrupted_transmission_reconciles_and_recovers_without_duplicates(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
        gateway: FakeSalesforceGatewayV2,
    ) -> None:
        run_id = uuid.uuid4()
        req = RunRequest(run_id=run_id, app_config_hash="h1")
        att = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        job_id = uuid.uuid4()
        comp_id = uuid.uuid4()
        cjob, binding = self._seed_canonical_job(engine, job_id, comp_id)

        now = datetime.now(timezone.utc)
        asmt_id = uuid.uuid4()
        asmt = Assessment(
            assessment_id=asmt_id,
            canonical_job_id=job_id,
            posting_revision=f"sha256:{'b'*64}",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Pass",
            rule_outcomes=[],
        )
        sel = AssessmentSelection(
            canonical_job_id=job_id,
            candidate_id=uuid.uuid4(),
            purpose="assessment",
            input_fingerprint="fp1",
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_token_1",
            is_selected_final=True,
            disposition=AssessmentDisposition.ELIGIBLE,
        )
        engine.pipeline_work.save_assessment_selection(sel)
        submission = build_sync_submission(
            selection=sel,
            assessment=asmt,
            canonical_job=cjob,
            binding=binding,
            run_id=run_id,
        )

        coordinator = SyncStageCoordinator(engine)

        # Plan submission first
        plan_results = coordinator.plan_submissions([submission], config)
        assert len(plan_results) == 1
        plan = plan_results[0].plan
        comp_step = [s for s in plan.steps if s.target_object == config.company_object][0]

        # Simulate network timeout during Company upsert where Salesforce actually received it
        # FakeSalesforceGatewayV2 commits the record into its memory store but returns RemoteOutcome.UNKNOWN
        gateway._simulate_lost_response_on_upsert = True

        # Attempt drain 1 -> Fails with UNKNOWN remote outcome
        drain_res_1 = coordinator.dispatcher.drain_due_work(gateway=gateway, config=config)
        assert drain_res_1.steps_failed >= 1

        # Uncertainty barrier MUST be retained on company lane!
        has_barrier = engine.sync_state.has_active_barrier(
            org_id=config.expected_org_id,
            target_object=config.company_object,
            entity_id=comp_id,
        )
        assert has_barrier is True

        # Attempt drain 2 without reconciliation -> blocked by barrier!
        drain_res_2 = coordinator.dispatcher.drain_due_work(gateway=gateway, config=config)
        assert drain_res_2.operations_claimed == 0

        # Now execute full sync stage (which runs reconcile_due_work first!)
        stage_res = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],  # Replay same submission
            config=config,
            gateway=gateway,
        )

        # Reconciliation must have confirmed the uncertain company step!
        assert stage_res.reconciliation_result is not None
        assert stage_res.reconciliation_result.steps_confirmed >= 1

        # Barrier cleared and Job step drained successfully!
        assert stage_res.sync_operations_succeeded == 1

        # Both Company and Job mappings now exist in local state
        comp_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.company_object, comp_id)
        job_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert comp_map is not None
        assert job_map is not None

    def test_stale_generation_token_rejected(
        self,
        engine: StorageEngine,
        config: SyncMappingConfig,
    ) -> None:
        job_id = uuid.uuid4()
        comp_id = uuid.uuid4()
        cjob, binding = self._seed_canonical_job(engine, job_id, comp_id)
        now = datetime.now(timezone.utc)

        # Active generation token advanced to "gen_2"
        engine.sync_state.register_selection_token(job_id, "gen_2")

        # Submission with stale "gen_1" arrives late
        asmt = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=job_id,
            posting_revision=f"sha256:{'b'*64}",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Pass",
            rule_outcomes=[],
        )
        sel = AssessmentSelection(
            canonical_job_id=job_id,
            candidate_id=uuid.uuid4(),
            purpose="assessment",
            input_fingerprint="fp1",
            assessment_id=asmt.assessment_id,
            evaluated_at=now,
            generation_token="gen_1",  # Stale!
            is_selected_final=True,
            disposition=AssessmentDisposition.ELIGIBLE,
        )
        submission = build_sync_submission(
            selection=sel,
            assessment=asmt,
            canonical_job=cjob,
            binding=binding,
        )

        coordinator = SyncStageCoordinator(engine)
        with pytest.raises(StaleSelectionError):
            coordinator.plan_submissions([submission], config)
