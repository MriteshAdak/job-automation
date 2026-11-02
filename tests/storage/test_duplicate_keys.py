"""Tests for duplicate-key rejection across repositories."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    DocumentApproval,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting, RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.runs import RunSummary
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError


class TestDuplicateKeys:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "dup_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_duplicate_raw_posting_source_key_rejected(self, engine: StorageEngine) -> None:
        sk = SourceKey(provider="arbeitnow", board_id="tech", source_posting_id="12345")
        now_dt = datetime.now(timezone.utc)
        raw1 = RawPosting(
            raw_payload_ref="path/to/raw1.json",
            raw_content_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            source_key=sk,
            fetch_time=now_dt,
            raw_payload="{}",
        )
        engine.raw_postings.save_raw_posting(raw1)

        raw2 = RawPosting(
            raw_payload_ref="path/to/raw2.json",
            raw_content_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            source_key=sk,  # Identical (provider, board_id, source_posting_id)
            fetch_time=now_dt,
            raw_payload="{}",
        )

        with pytest.raises(DuplicateKeyError) as exc_info:
            engine.raw_postings.save_raw_posting(raw2)

        assert "Duplicate source posting key" in str(exc_info.value)
        assert "arbeitnow" in str(exc_info.value)
        assert "12345" in str(exc_info.value)

    def test_duplicate_normalized_posting_source_key_rejected(
        self, engine: StorageEngine
    ) -> None:
        sk = SourceKey(provider="greenhouse", board_id="acme", source_posting_id="gh-99")
        now_dt = datetime.now(timezone.utc)
        np1 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            raw_reference="ref/raw.json",
            raw_content_hash="sha256:3333333333333333333333333333333333333333333333333333333333333333",
            company_name_hint="Acme GmbH",
            title="Backend Developer",
            description_clean="Clean text",
            source_url="https://example.com/job/1",
            workplace_type="onsite",
            observed_at=now_dt,
        )
        engine.canonical_jobs.save_normalized_posting(np1)

        np2 = NormalizedPosting(
            source_key=sk,            # Duplicate source key!
            normalizer_version="1.0",
            raw_reference="ref/raw2.json",
            raw_content_hash="sha256:4444444444444444444444444444444444444444444444444444444444444444",
            company_name_hint="Acme GmbH",
            title="Backend Developer",
            description_clean="Clean text",
            source_url="https://example.com/job/2",
            workplace_type="onsite",
            observed_at=now_dt,
        )
        with pytest.raises(DuplicateKeyError):
            engine.canonical_jobs.save_normalized_posting(np2)

    def test_duplicate_run_id_rejected(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id)
        with pytest.raises(DuplicateKeyError):
            engine.runs.create_run(run_id)

    def test_duplicate_sync_operation_id_rejected(self, engine: StorageEngine) -> None:
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
            job_title="Dev",
            company_name="Acme",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="OK",
            last_evaluated_at=now_dt,
        )
        op1 = SyncOperation(
            operation_id=op_id,
            canonical_job_id=job_id,
            payload_version="1",
            payload_fingerprint="sha256:5555555555555555555555555555555555555555555555555555555555555555",
            locally_owned_payload=payload,
        )
        engine.sync_outbox.enqueue_operation(op1)

        op2 = SyncOperation(
            operation_id=op_id,  # Duplicate operation_id
            canonical_job_id=job_id,
            payload_version="2",
            payload_fingerprint="sha256:6666666666666666666666666666666666666666666666666666666666666666",
            locally_owned_payload=payload,
        )
        with pytest.raises(DuplicateKeyError):
            engine.sync_outbox.enqueue_operation(op2)

    def test_duplicate_generation_request_id_rejected(self, engine: StorageEngine) -> None:
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

        req_id = uuid.uuid4()
        req1 = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_standard",
            created_at=now_dt,
        )
        engine.generation_requests.create_request(req1)

        req2 = GenerationRequest(
            request_id=req_id,  # Duplicate request_id
            canonical_job_id=job_id,
            document_type=DocumentType.COVER_LETTER,
            template_id="template_standard",
            created_at=now_dt,
        )
        with pytest.raises(DuplicateKeyError):
            engine.generation_requests.create_request(req2)

    def test_duplicate_artifact_id_rejected(self, engine: StorageEngine) -> None:
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

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="template_standard",
            created_at=now_dt,
        )
        engine.generation_requests.create_request(req)

        art_id = uuid.uuid4()
        art1 = Artifact(
            artifact_id=art_id,
            request_id=req_id,
            artifact_version=1,
            format="pdf",
            local_path="path/to/doc.pdf",
            content_hash="sha256:7777777777777777777777777777777777777777777777777777777777777777",
            size_bytes=1024,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=now_dt,
        )
        engine.artifacts.save_artifact(art1)

        art2 = Artifact(
            artifact_id=art_id,  # Duplicate
            request_id=req_id,
            artifact_version=2,
            format="docx",
            local_path="path/to/doc.docx",
            content_hash="sha256:8888888888888888888888888888888888888888888888888888888888888888",
            size_bytes=2048,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=now_dt,
        )
        with pytest.raises(DuplicateKeyError):
            engine.artifacts.save_artifact(art2)
