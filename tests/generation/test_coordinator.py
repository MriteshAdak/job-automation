"""Tests for staged generation coordination, dependency gates, and existing port integration (GEN-01-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    ContextStrategy,
    DocumentApproval,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import NormalizedPosting
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.ports import (
    DraftValidator,
    GenerationInputService,
)
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import (
    FreezeManifest,
    GenerationStage,
    StageStatus,
    ValidationReport,
)
from job_automation.storage.engine import StorageEngine
from tests.fakes.fake_services import FakeGenerator, FakeRendererDelivery
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class FakeInputService(GenerationInputService):
    """Fake GEN-02 implementation for testing GEN-01 coordination."""

    def __init__(self, canonical_job_id: uuid.UUID) -> None:
        self.canonical_job_id = canonical_job_id

    def prepare_freeze(
        self, request: GenerationRequest, freeze_op_id: str
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        manifest = FreezeManifest(
            manifest_id=f"manifest:{request.request_id}",
            manifest_hash="sha256:" + "1" * 64,
            canonical_job_id=self.canonical_job_id,
            posting_revision_id="rev-1",
            posting_revision_hash="hash-1",
            profile_version="prof-v1",
            policy_version="pol-v1",
            template_id=request.template_id,
            template_version="tmpl-v1",
            context_strategy=request.context_strategy,
            target_language=request.target_language,
            options_digest="sha256:" + "2" * 64,
            frozen_at=datetime.now(timezone.utc),
        )
        return manifest, None

    def reopen_freeze(
        self, manifest_id: str
    ) -> tuple[FreezeManifest | None, ClassifiedError | None]:
        return None, None

    def build_context(
        self, manifest: FreezeManifest, context_op_id: str
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        bundle = ContextBundle(
            strategy=manifest.context_strategy,
            profile_version=manifest.profile_version,
            posting_revision=manifest.posting_revision_hash,
            token_budget=4000,
            estimated_tokens=500,
        )
        return bundle, None


class FakeValidator(DraftValidator):
    """Fake GEN-04 validator."""

    def __init__(self, is_valid: bool = True, fatal_errors: list[str] | None = None) -> None:
        self.is_valid = is_valid
        self.fatal_errors = fatal_errors or []

    def validate_draft(
        self, draft: DraftDocument, manifest: FreezeManifest
    ) -> tuple[ValidationReport | None, ClassifiedError | None]:
        report = ValidationReport(
            is_valid=self.is_valid,
            fatal_errors=self.fatal_errors,
            warnings=["Subjective section present"],
            validated_draft_hash="sha256:" + "3" * 64,
        )
        return report, None


@pytest.fixture
def engine(tmp_path: Path) -> StorageEngine:
    eng = StorageEngine(db_path=tmp_path / "coord.db", raw_dir=tmp_path / "raw", artifacts_dir=tmp_path / "art")
    eng.initialize_schema()
    return eng


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID) -> None:
    now_utc = datetime.now(timezone.utc)
    cjob = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability=PostingAvailability.ACTIVE,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now_utc,
        last_seen_at=now_utc,
    )
    engine.canonical_jobs.save_canonical_job(cjob)


class TestGenerationCoordinator:
    def test_missing_gen02_fails_with_named_dependency_block_and_no_fabricated_context(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=None,  # GEN-02 ABSENT
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id="a00111111111111AAA",
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        final_req, status, err = coordinator.process_request(req)
        assert status == StageStatus.BLOCKED
        assert err is not None
        assert "GEN-02 input freezing service is absent" in err.message

        # Assert zero fabricated freeze association
        assert engine.generation_work.get_freeze_association(req_id) is None
        # Assert checkpoint is saved as BLOCKED
        chk = engine.generation_work.get_checkpoint(req_id, "freeze")
        assert chk is not None
        assert chk.status == StageStatus.BLOCKED

    def test_missing_downstream_stages_remain_visible_and_do_not_falsely_mark_ready(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        input_svc = FakeInputService(canonical_job_id=job_id)

        # Injected: GEN-02 only. Missing: GEN-03 (generator), GEN-04, GEN-05, GEN-06.
        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_svc,
            generator=None,  # GEN-03 ABSENT
            validator=None,
            renderer=None,
            deliverer=None,
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        final_req, status, err = coordinator.process_request(req)
        assert status == StageStatus.BLOCKED
        assert err is not None
        assert "GEN-03 draft generator absent" in err.message

        # Request must remain in RUNNING state (frozen), NEVER falsely marked ready_for_review!
        assert final_req.state == GenerationProcessing.RUNNING
        assert final_req.state != GenerationProcessing.READY_FOR_REVIEW

        # Remote Running was projected
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Running"

    def test_through_context_stops_after_context_and_does_not_claim_delivery(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)
        input_svc = FakeInputService(canonical_job_id=job_id)

        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_svc,
            generator=FakeGenerator(),
            validator=FakeValidator(),
            renderer=FakeRendererDelivery(),
            deliverer=FakeRendererDelivery(),
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        # Explicitly run through context only
        final_req, status, err = coordinator.process_request(req, stop_after_stage="context")
        assert status == StageStatus.COMPLETED
        assert err is None
        assert final_req.state == GenerationProcessing.RUNNING

        # Context checkpoint is completed
        chk_ctx = engine.generation_work.get_checkpoint(req_id, "context")
        assert chk_ctx is not None
        assert chk_ctx.status == StageStatus.COMPLETED

        # Later stages (draft, validation, rendering, delivery) were NOT run
        assert engine.generation_work.get_checkpoint(req_id, "draft") is None
        assert engine.generation_work.get_checkpoint(req_id, "delivery") is None

    def test_full_pipeline_through_existing_interfaces_reaches_ready_for_review(
        self, engine: StorageEngine
    ) -> None:
        gateway = FakeSalesforceGatewayV2()
        sf_id = "a00111111111111AAA"
        gateway.records["Generation_Request__c"] = {
            sf_id: {"Id": sf_id, "Status__c": "Pending"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)
        job_id = uuid.uuid4()
        _create_canonical_job(engine, job_id)

        input_svc = FakeInputService(canonical_job_id=job_id)
        generator = FakeGenerator()
        validator = FakeValidator(is_valid=True)
        renderer_delivery = FakeRendererDelivery()

        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_svc,
            generator=generator,
            validator=validator,
            renderer=renderer_delivery,
            deliverer=renderer_delivery,
        )

        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            salesforce_request_id=sf_id,
            canonical_job_id=job_id,
            document_type=DocumentType.CV,
            template_id="t1",
            state=GenerationProcessing.PENDING,
            created_at=datetime.now(timezone.utc),
        )
        engine.generation_requests.create_request(req)

        final_req, status, err = coordinator.process_request(req)
        assert status == StageStatus.COMPLETED
        assert err is None
        assert final_req.state == GenerationProcessing.READY_FOR_REVIEW
        assert final_req.completed_at is not None

        # Verify remote status reached Ready_for_Review
        assert gateway.records["Generation_Request__c"][sf_id]["Status__c"] == "Ready_for_Review"

        # Verify checkpoints exist for all 6 stages
        stages = ["freeze", "context", "draft", "validation", "rendering", "delivery"]
        for s in stages:
            chk = engine.generation_work.get_checkpoint(req_id, s)
            assert chk is not None, f"Missing checkpoint for {s}"
            assert chk.status == StageStatus.COMPLETED

        # Verify artifact deliveries recorded
        deliveries = engine.generation_work.list_delivery_records(req_id)
        assert len(deliveries) == 2  # docx and pdf
        assert all(d.delivery_status == "delivered" for d in deliveries)
