"""Tests for candidate field preservation and local backup scans (RUN-01-S07)."""

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
from job_automation.orchestration.records import (
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.orchestration.sync_bridge import build_sync_submission
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.salesforce.sync_records import RemoteEntityMapping
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "sync.example.json"


class TestCandidateBackup:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "candidate_backup_test.db"
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
        company_name: str = "Backup Corp",
        title: str = "Staff Backend Engineer",
    ) -> tuple[CanonicalJob, PostingBinding]:
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")
        rev_id = uuid.uuid4()
        rev_hash = f"sha256:{'c'*64}"
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

    def test_candidate_fields_snapshotted_before_update_and_preserved(
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
        # Pre-seed remote mapping in Salesforce
        remote_job_id = "a00000000000001AAA"
        remote_comp_id = "a00000000000002AAA"
        engine.sync_state.save_remote_mapping(
            RemoteEntityMapping(
                org_id=config.expected_org_id,
                object_name=config.job_object,
                entity_id=job_id,
                external_id=str(job_id),
                salesforce_id=remote_job_id,
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
                salesforce_id=remote_comp_id,
                confirmed_sequence=1,
                acknowledged_at=now,
            )
        )

        # In fake gateway, seed record with candidate notes and interview date
        gateway.records.setdefault(config.job_object, {})
        gateway.external_ids.setdefault(config.job_object, {})
        gateway.records[config.job_object][remote_job_id] = {
            "Id": remote_job_id,
            config.job_external_id_field: str(job_id),
            "Application_Progress__c": "Interviewing",
            "Candidate_Notes__c": "Strong candidate, round 2 scheduled",
            "Candidate_Decision__c": "Proceed",
            "Follow_Up_Date__c": "2026-11-05",
            "Interview_Date__c": "2026-11-01",
        }
        gateway.external_ids[config.job_object][str(job_id)] = remote_job_id

        # Candidate assessment update
        asmt_id = uuid.uuid4()
        asmt = Assessment(
            assessment_id=asmt_id,
            canonical_job_id=job_id,
            posting_revision=f"sha256:{'c'*64}",
            profile_version="v2",
            policy_version="v2",
            assessment_method=AssessmentMethod.RULES,
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="Pass updated",
            rule_outcomes=[],
        )
        sel = AssessmentSelection(
            canonical_job_id=job_id,
            candidate_id=uuid.uuid4(),
            purpose="assessment",
            input_fingerprint="fp2",
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_token_2",
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
        result = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],
            config=config,
            gateway=gateway,
            run_candidate_backup=True,
        )

        assert result.sync_operations_succeeded == 1
        # Check that candidate snapshot was saved locally before the write
        snapshots = engine.candidate_snapshots.get_snapshots_for_job(job_id)
        assert len(snapshots) >= 1
        latest_snap = snapshots[0]
        assert latest_snap.candidate_fields.get("Application_Progress__c") == "Interviewing"
        assert latest_snap.candidate_fields.get("Candidate_Notes__c") == "Strong candidate, round 2 scheduled"

        # Check that outbound upsert did NOT overwrite the candidate fields in Salesforce
        remote_rec = gateway.records[config.job_object][remote_job_id]
        assert remote_rec["Application_Progress__c"] == "Interviewing"
        assert remote_rec["Candidate_Notes__c"] == "Strong candidate, round 2 scheduled"

    def test_backup_failure_does_not_fail_confirmed_writes(
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
            posting_revision=f"sha256:{'c'*64}",
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

        # Mock the backup service to fail during scan
        class FailingBackupService:
            def backup_candidate_fields(self, *args, **kwargs):
                raise RuntimeError("Backup query timeout")

        coordinator.backup_service = FailingBackupService()

        result = coordinator.execute_sync(
            request=req,
            attempt=att,
            submissions=[submission],
            config=config,
            gateway=gateway,
            run_candidate_backup=True,
        )

        # Write must still succeed!
        assert result.sync_operations_succeeded == 1
        # Backup failure recorded in errors, but confirmed write remains confirmed
        assert result.backup_result is not None
        assert result.backup_result.is_complete is False
        assert any("Backup query timeout" in err.message for err in result.errors)

