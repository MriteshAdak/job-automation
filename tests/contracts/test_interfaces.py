"""Tests for service-independent interface boundaries and fake conformance."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.artifacts import Artifact, DraftDocument
from job_automation.contracts.enums import (
    AcquisitionMethod,
    ContextStrategy,
    DocumentType,
    FetchOutcome,
    GenerationProcessing,
    InventorySemantics,
)
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.generation import GenerationRequest
from job_automation.contracts.interfaces import (
    Adapter,
    Assessor,
    ContextSelector,
    Generator,
    IdentityResolver,
    ModelProvider,
    Normalizer,
    RendererDelivery,
    RuleEvaluator,
    SalesforceGateway,
)
from job_automation.contracts.models import ModelCall
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.contracts.sources import SourceConfig
from job_automation.contracts.sync import SyncOperation, SyncPayload
from tests.fakes.fake_services import (
    FakeAdapter,
    FakeAssessor,
    FakeContextSelector,
    FakeGenerator,
    FakeIdentityResolver,
    FakeModelProvider,
    FakeNormalizer,
    FakeRendererDelivery,
    FakeRuleEvaluator,
    FakeSalesforceGateway,
)


class TestInterfaces:
    def test_protocol_isinstance_conformance(self) -> None:
        """Verify all 10 fake implementations satisfy runtime_checkable protocols."""
        assert isinstance(FakeAdapter(), Adapter)
        assert isinstance(FakeNormalizer(), Normalizer)
        assert isinstance(FakeIdentityResolver(), IdentityResolver)
        assert isinstance(FakeRuleEvaluator(), RuleEvaluator)
        assert isinstance(FakeContextSelector(), ContextSelector)
        assert isinstance(FakeModelProvider(), ModelProvider)
        assert isinstance(FakeAssessor(), Assessor)
        assert isinstance(FakeSalesforceGateway(), SalesforceGateway)
        assert isinstance(FakeGenerator(), Generator)
        assert isinstance(FakeRendererDelivery(), RendererDelivery)

    def test_adapter_and_normalizer_flow(self) -> None:
        sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="101")
        now = datetime.now(timezone.utc)
        raw = RawPosting(
            raw_payload_ref="ref/101.json",
            raw_content_hash="sha256:" + "0" * 64,
            source_key=sk,
            fetch_time=now,
            raw_payload='{"title": "Dev"}',
        )
        adapter = FakeAdapter(raw_postings=[raw])
        config = SourceConfig(
            source_key="arbeitnow",
            provider="arbeitnow",
            board_id="default",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.example.com",
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )

        page = adapter.fetch_page(config)
        assert len(page.items) == 1
        assert page.continuation_out is not None
        assert page.continuation_out.value == "cursor_next"
        assert not page.exhausted

        draft_result = adapter.draft_posting(page.items[0])
        assert draft_result.draft is not None
        assert isinstance(draft_result.draft, SourceJobDraft)
        draft = draft_result.draft

        # Normalizer success
        normalizer = FakeNormalizer(should_fail=False)
        np, issues = normalizer.normalize(draft)
        assert np is not None
        assert len(issues) == 0

        # Normalizer failure
        failing_normalizer = FakeNormalizer(should_fail=True)
        failed_np, fail_issues = failing_normalizer.normalize(draft)
        assert failed_np is None
        assert len(fail_issues) == 1
        assert fail_issues[0].field_path == "title"

    def test_context_selector_budget_error(self) -> None:
        snapshot = ProfileSnapshot(
            candidate_id=uuid.uuid4(),
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="self",
                approved_at=datetime.now(timezone.utc),
            ),
            explicit_eligibility=CandidateEligibility(),
        )

        # Success case
        selector = FakeContextSelector(budget_overflow=False)
        bundle, err = selector.select_context(
            requirements=["Python"],
            profile=snapshot,
            strategy=ContextStrategy.JSON,
            token_budget=4000,
        )
        assert bundle is not None
        assert err is None

        # Overflow case
        selector_overflow = FakeContextSelector(budget_overflow=True)
        bundle_fail, err_fail = selector_overflow.select_context(
            requirements=["Python"],
            profile=snapshot,
            strategy=ContextStrategy.JSON,
            token_budget=100,
        )
        assert bundle_fail is None
        assert err_fail is not None
        assert err_fail.category == ErrorCategory.CONTEXT_BUDGET

    def test_model_provider_generation_and_embedding(self) -> None:
        provider = FakeModelProvider()
        call = ModelCall(
            call_id=uuid.uuid4(),
            operation_type="relevance_assessment",
            model_identifier="test-model",
            prompt_version="p1",
            context_limit=4096,
            input_fingerprint="sha256:" + "0" * 64,
        )
        res = provider.generate(call)
        assert res.parsed_output is not None
        assert res.parsed_output["disposition"] == "eligible"

        # Embedding call
        emb_res, emb_err = provider.embed(["python developer", "cloud engineer"], "text-embed-3")
        assert emb_err is None
        assert emb_res is not None
        assert len(emb_res.vectors) == 2
        assert emb_res.dimension == 384

        # Transient error simulation
        err_provider = FakeModelProvider(simulate_transient_error=True)
        err_res = err_provider.generate(call)
        assert err_res.error is not None
        assert err_res.error.category == ErrorCategory.TRANSIENT_SERVICE
        assert err_res.error.recoverable is True

    def test_gateway_and_renderer_delivery(self) -> None:
        gateway = FakeSalesforceGateway()
        now = datetime.now(timezone.utc)
        op = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            payload_version="v1",
            payload_fingerprint="sha256:" + "0" * 64,
            locally_owned_payload=SyncPayload(
                canonical_job_id=uuid.uuid4(),
                job_title="Engineer",
                company_name="Corp",
                availability="active",
                assessment_disposition="eligible",
                assessment_reasons="Match",
                last_evaluated_at=now,
            ),
        )

        remote_id, err = gateway.execute_sync(op)
        assert remote_id == "a00XXXXXXXXXXXXXXX"
        assert err is None
        assert gateway.last_operation_id == op.operation_id

        # Renderer and Delivery
        renderer = FakeRendererDelivery()
        gen = FakeGenerator()
        req = GenerationRequest(
            request_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            document_type=DocumentType.CV,
            template_id="t1",
            created_at=now,
        )
        draft, _ = gen.generate_draft(req, None)
        artifact, rend_err = renderer.render(draft, "docx", r"C:\tmp\test.docx")
        assert rend_err is None
        assert artifact is not None
        assert artifact.delivery_status == "local_only"

        delivered, del_err = renderer.deliver(artifact, gateway)
        assert del_err is None
        assert delivered.delivery_status == "delivered"
        assert delivered.remote_file_id is not None

