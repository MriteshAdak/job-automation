"""Comprehensive contract round-trip tests for all storage repositories."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    DocumentApproval,
    DocumentType,
    FetchOutcome,
    HardCriterionResult,
    InventorySemantics,
    PipelineStage,
    PostingAvailability,
    RunStatus,
    SyncOperationState,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import FetchManifest, NormalizedPosting, RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.runs import RunSummary
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.storage.engine import StorageEngine
from job_automation.storage.migrations import ALL_MIGRATIONS


class TestRepositories:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "repos_test.db"
        raw_dir = tmp_path / "raw"
        artifacts_dir = tmp_path / "artifacts"
        eng = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=artifacts_dir)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_run_ledger_roundtrip(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)

        engine.runs.create_run(run_id=run_id, start_time=now_dt, status="running")
        engine.runs.record_stage(
            run_id=run_id,
            stage_name="fetch",
            status=PipelineStage.RUNNING,
            started_at=now_dt,
        )

        stages = engine.runs.get_stages(run_id)
        assert len(stages) == 1
        assert stages[0]["stage_name"] == "fetch"
        assert stages[0]["status"] == PipelineStage.RUNNING.value

        # Complete run
        summary = RunSummary(
            run_id=run_id,
            start_time=now_dt,
            end_time=now_dt,
            status=RunStatus.SUCCESS,
            source_counts={"arbeitnow": 20},
            source_postings_count=20,
            canonical_jobs_new=5,
            eligible_count=2,
            review_count=1,
            rejected_count=2,
        )
        engine.runs.complete_run(summary)

        fetched = engine.runs.get_run(run_id)
        assert fetched is not None
        assert fetched.run_id == run_id
        assert fetched.status == RunStatus.SUCCESS
        assert fetched.source_postings_count == 20
        assert fetched.canonical_jobs_new == 5

        all_runs = engine.runs.list_runs()
        assert len(all_runs) >= 1
        assert all_runs[0].run_id == run_id

    def test_raw_postings_and_manifest_roundtrip(self, engine: StorageEngine) -> None:
        sk = SourceKey(provider="arbeitnow", board_id="tech", source_posting_id="post_999")
        now_dt = datetime.now(timezone.utc)
        payload_text = '{"title": "Staff Engineer", "tags": ["python", "azure"]}'

        ref, content_hash = engine.filestore.save_raw_payload(
            provider=sk.provider,
            board_id=sk.board_id,
            source_posting_id=sk.source_posting_id,
            payload=payload_text,
        )

        raw = RawPosting(
            raw_payload_ref=ref,
            raw_content_hash=content_hash,
            source_key=sk,
            fetch_time=now_dt,
            raw_headers={"content-type": "application/json"},
            raw_payload=payload_text,
        )
        engine.raw_postings.save_raw_posting(raw)

        fetched = engine.raw_postings.get_raw_posting(sk)
        assert fetched is not None
        assert fetched.source_key == sk
        assert fetched.raw_payload == payload_text
        assert fetched.raw_content_hash == content_hash

        # Fetch manifest
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id)
        manifest = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow_tech",
            scope_id="tech_jobs",
            start_time=now_dt,
            end_time=now_dt,
            page_count=2,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            raw_response_refs=[ref],
            observed_posting_identities=["post_999"],
        )
        engine.raw_postings.save_manifest(manifest)

        manifests = engine.raw_postings.get_manifests_for_run(run_id)
        assert len(manifests) == 1
        assert manifests[0].source_key == "arbeitnow_tech"
        assert manifests[0].outcome == FetchOutcome.COMPLETE

    def test_canonical_job_and_revisions_roundtrip(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="item_1")

        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=job_id,
            source_key=sk,
            content_hash="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            title="Senior Architect",
            first_seen_at=now_dt,
            last_seen_at=now_dt,
            availability=PostingAvailability.ACTIVE,
        )
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Cloud Solutions GmbH",
            current_revision_id=rev_id,
            first_seen_at=now_dt,
            last_seen_at=now_dt,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk],
            revisions=[rev],
        )

        engine.canonical_jobs.save_canonical_job(job)

        fetched = engine.canonical_jobs.get_canonical_job(job_id)
        assert fetched is not None
        assert fetched.canonical_job_id == job_id
        assert fetched.company_name == "Cloud Solutions GmbH"

        # Lookup by source key
        found = engine.canonical_jobs.find_by_source_key(sk)
        assert found is not None
        assert found.canonical_job_id == job_id

        # List revisions
        revisions = engine.canonical_jobs.get_revisions(job_id)
        assert len(revisions) == 1
        assert revisions[0].revision_id == rev_id

        # List jobs by availability
        active_jobs = engine.canonical_jobs.list_jobs(availability=PostingAvailability.ACTIVE)
        assert len(active_jobs) >= 1
        assert active_jobs[0].canonical_job_id == job_id

        # Normalized posting roundtrip
        np = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            raw_reference=f"raw/{sk.provider}/{sk.board_id}/{sk.source_posting_id}.json",
            raw_content_hash="sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            company_name_hint="Cloud Solutions",
            title="Senior Architect",
            description_clean="Cleaned job spec",
            source_url="https://example.com/job/item_1",
            workplace_type="remote",
            observed_at=now_dt,
        )
        engine.canonical_jobs.save_normalized_posting(np)
        loaded_np = engine.canonical_jobs.get_normalized_posting(sk)
        assert loaded_np is not None
        assert loaded_np.title == "Senior Architect"
        assert loaded_np.company_name_hint == "Cloud Solutions"

    def test_assessment_roundtrip(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Enterprise AG",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        assessment_id = uuid.uuid4()
        rule = RuleOutcome(
            criterion_id="hard_01",
            criterion_name="Work Authorization",
            result=HardCriterionResult.PASS,
            reason="Authorized to work in Germany",
        )
        assessment = Assessment(
            assessment_id=assessment_id,
            canonical_job_id=job_id,
            posting_revision="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            profile_version="2026-10",
            policy_version="2026-10",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[rule],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            final_disposition=AssessmentDisposition.ELIGIBLE,
            summary_reason="All hard criteria passed",
        )

        engine.assessments.save_assessment(assessment)

        fetched = engine.assessments.get_assessment(assessment_id)
        assert fetched is not None
        assert fetched.assessment_id == assessment_id
        assert len(fetched.rule_outcomes) == 1
        assert fetched.rule_outcomes[0].result == HardCriterionResult.PASS

        latest = engine.assessments.get_latest_assessment(job_id)
        assert latest is not None
        assert latest.assessment_id == assessment_id

        all_for_job = engine.assessments.get_assessments_for_job(job_id)
        assert len(all_for_job) == 1
        assert all_for_job[0].assessment_id == assessment_id

    def test_sync_outbox_roundtrip(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        op_id = uuid.uuid4()
        payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Lead Architect",
            company_name="Acme",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="High score",
            last_evaluated_at=now_dt,
        )
        op = SyncOperation(
            operation_id=op_id,
            canonical_job_id=job_id,
            payload_version="1.0",
            payload_fingerprint="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            locally_owned_payload=payload,
            state=SyncOperationState.PENDING,
        )
        engine.sync_outbox.enqueue_operation(op)

        pending = engine.sync_outbox.get_pending_operations()
        assert len(pending) == 1
        assert pending[0].operation_id == op_id

        # Update operation to succeeded with remote record id
        updated_op = op.model_copy(
            update={
                "state": SyncOperationState.SUCCEEDED,
                "remote_record_id": "a001x00000abcXYZ",
                "remote_acknowledged_at": now_dt,
            }
        )
        engine.sync_outbox.update_operation(updated_op)

        saved = engine.sync_outbox.get_operation(op_id)
        assert saved is not None
        assert saved.state == SyncOperationState.SUCCEEDED
        assert saved.remote_record_id == "a001x00000abcXYZ"

    def test_generation_request_and_artifact_roundtrip(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Tech Solutions",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="cv_modern_de",
            context_strategy=ContextStrategy.JSON,
            created_at=now_dt,
        )
        engine.generation_requests.create_request(req)

        # Claim request
        frozen = FrozenInputVersions(
            posting_revision="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
            profile_version="v2026.1",
            policy_version="v2026.1",
            template_version="1.0",
        )
        claimed = engine.generation_requests.claim_request(req_id, frozen)
        assert claimed.state.value == "running"
        assert claimed.claimed_at is not None

        # Create physical artifact
        art_id = uuid.uuid4()
        docx_bytes = b"SampleDOCXBytes"
        local_path, content_hash, size = engine.filestore.save_artifact_file(
            request_id=req_id,
            filename="Lebenslauf.docx",
            content=docx_bytes,
        )

        artifact = Artifact(
            artifact_id=art_id,
            request_id=req_id,
            artifact_version=1,
            format="docx",
            local_path=local_path,
            content_hash=content_hash,
            size_bytes=size,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=now_dt,
        )
        engine.artifacts.save_artifact(artifact)

        fetched_art = engine.artifacts.get_artifact(art_id)
        assert fetched_art is not None
        assert fetched_art.size_bytes == len(docx_bytes)
        assert fetched_art.delivery_status == "local_only"

        # Update delivery status
        engine.artifacts.update_delivery_status(
            artifact_id=art_id,
            remote_file_id="0691x00000xyzABC",
            delivery_status="delivered",
        )
        delivered_art = engine.artifacts.get_artifact(art_id)
        assert delivered_art is not None
        assert delivered_art.remote_file_id == "0691x00000xyzABC"
        assert delivered_art.delivery_status == "delivered"

        # List artifacts for request
        artifacts_list = engine.artifacts.list_artifacts_for_request(req_id)
        assert len(artifacts_list) == 1
        assert artifacts_list[0].artifact_id == art_id

    def test_engine_context_manager(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ctx_test.db"
        with StorageEngine(db_path=db_path) as eng:
            eng.initialize_schema()
            assert eng.get_schema_version() == len(ALL_MIGRATIONS)
        # After exit, connection is closed
        assert eng._conn is None
