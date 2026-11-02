"""Tests for C12 SyncOperation, C13 GenerationRequest, C14 DraftDocument/Artifact,
and C15 RunSummary contracts.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.artifacts import (
    Artifact,
    DocumentClaim,
    DraftDocument,
    SubjectiveSection,
)
from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    DocumentApproval,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
    RunStatus,
    SyncOperationState,
)
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.generation import (
    FrozenInputVersions,
    GenerationRequest,
)
from job_automation.contracts.runs import RunSummary
from job_automation.contracts.sync import SyncOperation, SyncPayload


class TestWorkRecords:
    def test_c12_sync_operation_machine_payload_only(self) -> None:
        can_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        payload = SyncPayload(
            canonical_job_id=can_id,
            job_title="Lead Python Architect",
            company_name="Enterprise AG",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            relevance_score=92.5,
            score_scale="0-100",
            assessment_reasons="Strong architecture experience match",
            source_urls=["https://example.com/jobs/lead-python"],
            last_evaluated_at=now,
        )

        op1 = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=can_id,
            payload_version="2026-10-27T10:00:00Z",
            payload_fingerprint="sha256:" + "c" * 64,
            locally_owned_payload=payload,
            attempt_count=0,
            state=SyncOperationState.PENDING,
        )

        op2 = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=can_id,
            payload_version="2026-10-27T11:00:00Z",
            payload_fingerprint="sha256:" + "d" * 64,
            locally_owned_payload=payload,
            attempt_count=1,
            state=SyncOperationState.RETRY_WAIT,
        )

        assert op1.operation_id != op2.operation_id
        assert op1.canonical_job_id == op2.canonical_job_id
        assert op1.payload_version != op2.payload_version

    def test_c13_generation_request_defaults_and_frozen_inputs(self) -> None:
        can_id = uuid.uuid4()
        req_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Default allow_unavailable_job is False
        req_pending = GenerationRequest(
            request_id=req_id,
            canonical_job_id=can_id,
            document_type=DocumentType.CV,
            template_id="modern_de_v1",
            state=GenerationProcessing.PENDING,
            created_at=now,
        )
        assert req_pending.allow_unavailable_job is False
        assert req_pending.frozen_input_versions is None

        # Running state requires frozen_input_versions
        with pytest.raises(ValidationError, match="must have frozen_input_versions"):
            GenerationRequest(
                request_id=req_id,
                canonical_job_id=can_id,
                document_type=DocumentType.CV,
                template_id="modern_de_v1",
                state=GenerationProcessing.RUNNING,  # Missing frozen inputs!
                created_at=now,
            )

        # Valid running state with frozen inputs
        frozen = FrozenInputVersions(
            posting_revision="rev-sha-123",
            profile_version="v2026.1",
            policy_version="pol-1.0",
            template_version="tpl-1.0",
        )
        req_running = GenerationRequest(
            request_id=req_id,
            canonical_job_id=can_id,
            document_type=DocumentType.CV,
            template_id="modern_de_v1",
            state=GenerationProcessing.RUNNING,
            created_at=now,
            claimed_at=now,
            frozen_input_versions=frozen,
        )
        assert req_running.frozen_input_versions is not None

        # Deliberate regeneration links predecessor
        new_req_id = uuid.uuid4()
        req_regen = GenerationRequest(
            request_id=new_req_id,
            canonical_job_id=can_id,
            document_type=DocumentType.CV,
            template_id="modern_de_v1",
            state=GenerationProcessing.PENDING,
            created_at=now,
            predecessor_request_id=req_id,
        )
        assert req_regen.predecessor_request_id == req_id
        assert req_regen.request_id != req_id

    def test_c14_claims_and_artifact_delivery_vs_approval(self) -> None:
        req_id = uuid.uuid4()
        fact_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        frozen = FrozenInputVersions(
            posting_revision="rev-123",
            profile_version="v2026.1",
            policy_version="pol-1.0",
            template_version="tpl-1.0",
        )

        candidate_claim = DocumentClaim(
            claim_id="claim_1",
            text="Over 7 years of Python experience building distributed systems",
            evidence_reference=CandidateEvidenceReference(
                profile_version="v2026.1",
                fact_id=fact_id,
            ),
        )

        job_claim = DocumentClaim(
            claim_id="claim_2",
            text="Matches requirement for experience with cloud databases",
            evidence_reference=JobEvidenceReference(
                posting_revision="rev-123",
                field_path="requirements",
                quotation="Experience with cloud data platforms is desired",
            ),
        )

        draft = DraftDocument(
            request_id=req_id,
            document_type=DocumentType.CV,
            document_version="v1.0",
            title="Lebenslauf — Senior Python Engineer",
            candidate_name="Max Mustermann",
            target_role="Senior Python Engineer",
            target_company="Enterprise AG",
            structured_claims=[candidate_claim, job_claim],
            subjective_sections=[
                SubjectiveSection(
                    section_title="Profil & Motivation",
                    text="Passionate software craftsman dedicated to high-quality code...",
                    requires_human_review=True,
                )
            ],
            frozen_inputs=frozen,
        )

        assert len(draft.structured_claims) == 2
        assert draft.subjective_sections[0].requires_human_review is True

        # Artifact: delivered to Salesforce, but still in draft approval state!
        win_path = r"C:\Users\Example\Job Automation Daten\Entwürfe\CV.docx"
        artifact = Artifact(
            artifact_id=uuid.uuid4(),
            request_id=req_id,
            artifact_version=1,
            format="docx",
            local_path=win_path,
            content_hash="sha256:" + "e" * 64,
            size_bytes=42000,
            remote_file_id="069XXXXXXXXXXXXXXX",
            delivery_status="delivered",
            approval_status=DocumentApproval.DRAFT,  # Delivery != approval!
            reconciliation_marker=f"req-{req_id}-v1",
            created_at=now,
        )

        assert artifact.delivery_status == "delivered"
        assert artifact.approval_status == DocumentApproval.DRAFT
        assert artifact.local_path == win_path

    def test_c15_run_summary_counts_and_units(self) -> None:
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        summary = RunSummary(
            run_id=run_id,
            start_time=now,
            end_time=now,
            status=RunStatus.SUCCESS,
            source_counts={"arbeitnow_de": 3},
            source_postings_count=3,  # 3 source postings
            canonical_jobs_new=2,     # 2 canonical jobs
            canonical_jobs_updated=0,
            canonical_jobs_duplicate=1,
            eligible_count=1,
            review_count=1,
            rejected_count=0,
            sync_operations_succeeded=2,
            sync_operations_failed=0,
        )

        assert summary.source_postings_count == 3
        assert summary.canonical_jobs_new == 2
        assert summary.status == RunStatus.SUCCESS

        # Negative count must fail
        with pytest.raises(ValidationError):
            RunSummary(
                run_id=run_id,
                start_time=now,
                end_time=now,
                status=RunStatus.SUCCESS,
                source_postings_count=-1,
            )

