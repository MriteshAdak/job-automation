"""Tests for SyncStageCoordinator and sync_bridge integration (RUN-01-S07)."""

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
    SyncOperationState,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.orchestration.records import (
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.orchestration.sync_bridge import (
    build_refresh_submission,
    build_sync_submission,
)
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.salesforce.sync_errors import SyncValidationError
from job_automation.salesforce.sync_records import (
    PublicationDecision,
    PublicationPurpose,
    RemoteEntityMapping,
)
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "sync.example.json"


class TestSyncIntegration:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_stage_test.db"
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
        company_name: str = "Acme Corp",
        title: str = "Senior Python Engineer",
        revision_hash: str = f"sha256:{'a'*64}",
        source_url: str = "https://example.com/job/1",
        availability: PostingAvailability = PostingAvailability.ACTIVE,
    ) -> tuple[CanonicalJob, PostingBinding]:
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")
        rev_id = uuid.uuid4()
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=job_id,
            source_key=sk,
            content_hash=revision_hash,
            title=title,
            first_seen_at=now,
            last_seen_at=now,
            source_urls=[source_url],
            availability=availability,
        )
        cjob = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name=company_name,
            availability=availability,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[rev],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url=source_url,
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
            normalized_content_hash=revision_hash,
            raw_reference="raw/p1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            source_key=sk,
            c06_snapshot=c06,
        )
        engine.pipeline_work.save_posting_binding(binding)
        return cjob, binding

    def test_new_eligible_job_publishes_to_salesforce(
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
            posting_revision=f"sha256:{'a'*64}",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Pass",
            rule_outcomes=[],
        )
        # Note: commit_assessment_and_plan will persist the assessment in sync_state if not already present
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
        assert submission.job_title == "Senior Python Engineer"
        assert submission.source_urls == ["https://example.com/job/1"]
        assert submission.evaluated_at == now
        assert submission.generation_token == "gen_token_1"

        coordinator = SyncStageCoordinator(engine)
        result = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],
            config=config,
            gateway=gateway,
        )

        assert result.plans_created == 1
        assert result.published_initial == 1
        assert result.sync_operations_succeeded == 1
        assert result.sync_operations_failed == 0
        assert len(result.errors) == 0

        # Gateway received 2 upserts: Company first, then Job
        assert gateway.physical_upsert_count == 2
        assert len(gateway.upsert_requests) == 2
        assert gateway.upsert_requests[0].object_name == config.company_object
        assert gateway.upsert_requests[1].object_name == config.job_object

        # Remote entity mapping persisted
        comp_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.company_object, comp_id)
        job_map = engine.sync_state.get_remote_mapping(config.expected_org_id, config.job_object, job_id)
        assert comp_map is not None
        assert job_map is not None

    def test_new_rejected_job_stays_local_only(
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
            posting_revision=f"sha256:{'a'*64}",
            profile_version="v1",
            policy_version="v1",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.REJECTED,
            final_disposition=AssessmentDisposition.REJECTED,
            summary_reason="Rejected by hard criteria",
            rule_outcomes=[],
        )
        sel = AssessmentSelection(
            canonical_job_id=job_id,
            candidate_id=uuid.uuid4(),
            purpose="assessment",
            input_fingerprint="fp_rej",
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_token_rej",
            is_selected_final=True,
            disposition=AssessmentDisposition.REJECTED,
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
        result = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],
            config=config,
            gateway=gateway,
        )

        assert result.plans_created == 1
        assert result.local_only_rejected == 1
        assert result.published_initial == 0
        assert result.sync_operations_succeeded == 0
        # No remote upserts occurred
        assert gateway.physical_upsert_count == 0

    def test_tracked_job_updates_even_when_rejected(
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
        # Pre-seed remote mapping (job is already tracked)
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.job_object,
                entity_id=job_id,
                external_id=str(job_id),
                salesforce_id="a00000000000001AAA",
                confirmed_sequence=1,
                acknowledged_at=now,
            )
        )
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.company_object,
                entity_id=comp_id,
                external_id=str(comp_id),
                salesforce_id="a00000000000002AAA",
                confirmed_sequence=1,
                acknowledged_at=now,
            )
        )

        # Candidate later marks policy or job becomes rejected
        asmt_id = uuid.uuid4()
        asmt = Assessment(
            assessment_id=asmt_id,
            canonical_job_id=job_id,
            posting_revision=f"sha256:{'a'*64}",
            profile_version="v2",
            policy_version="v2",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.REJECTED,
            final_disposition=AssessmentDisposition.REJECTED,
            summary_reason="Changed preference",
            rule_outcomes=[],
        )
        sel = AssessmentSelection(
            canonical_job_id=job_id,
            candidate_id=uuid.uuid4(),
            purpose="assessment",
            input_fingerprint="fp_tracked_rej",
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_token_v2",
            is_selected_final=True,
            disposition=AssessmentDisposition.REJECTED,
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
        result = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],
            config=config,
            gateway=gateway,
        )

        # Tracked job MUST update even though rejected!
        assert result.plans_created == 1
        assert result.updated_tracked == 1
        assert result.sync_operations_succeeded == 1
        assert gateway.physical_upsert_count == 1  # Only Job update needed since company already mapped
