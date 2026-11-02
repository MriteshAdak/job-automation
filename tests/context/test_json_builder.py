"""End-to-end tests for JsonContextBuilder, success invariants, error categories, and absence of fallback."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.measurement import (
    ConservativeCharRatioEstimator,
    ExactTokenCounter,
)
from job_automation.context.records import JsonContextRequest
from job_automation.contracts.enums import (
    ContextStrategy,
    EvidenceFactKind,
    WorkplaceType,
)
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.fakes.context_measurement import FakeTokenCounter


def create_builder_test_fixture() -> tuple[ProfileSnapshot, NormalizedPosting, uuid.UUID, str, dict[str, uuid.UUID]]:
    cid = uuid.uuid4()
    f1 = uuid.uuid4()
    f2 = uuid.uuid4()
    f_private = uuid.uuid4()
    f_restricted = uuid.uuid4()

    now = datetime.now(timezone.utc)
    rev_hash = "sha256:" + "c" * 64
    job_id = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=f1,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Python Backend Engineer",
            organization="Tech GmbH",
            start_date=PrecisionDate(value="2020", precision="year"),
            skills=["Python", "FastAPI"],
            claims=["Designed event-driven backend services"],
            provenance="arbeitszeugnis_2024.pdf",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=f2,
            kind=EvidenceFactKind.EDUCATION,
            title="M.Sc. Software Engineering",
            organization="Uni Heidelberg",
            start_date=PrecisionDate(value="2018", precision="year"),
            end_date=PrecisionDate(value="2020", precision="year"),
            skills=["Distributed Systems"],
            claims=["Master thesis on distributed consensus"],
            provenance="urkunde.pdf",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=f_private,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Private Historical Role",
            claims=["PRIVATE_MARKER"],
            provenance="attestation",
            allowed_uses=[],
        ),
        CandidateFact(
            fact_id=f_restricted,
            kind=EvidenceFactKind.PROJECT,
            title="Restricted Side Project",
            claims=["RESTRICTED_MARKER"],
            provenance="attestation",
            allowed_uses=["cv"],  # Allowed for cv, NOT assessment
        ),
    ]

    snapshot = ProfileSnapshot(
        candidate_id=cid,
        profile_version="v2026.1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate",
            approved_at=now,
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            remote_eligible=True,
            min_salary=MoneyAmount(amount=Decimal("85000"), currency="EUR"),
        ),
        evidence_records=facts,
    )

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="101"),
        normalizer_version="1.0",
        raw_reference="ref_101",
        raw_content_hash=rev_hash,
        company_name_hint="FinTech AG",
        title="Senior Python Engineer",
        description_clean="We are looking for a Senior Python Engineer experienced in backend architecture.",
        workplace_type=WorkplaceType.HYBRID,
        source_url="https://example.com/job/101",
        observed_at=now,
    )

    id_map = {
        "f1": f1,
        "f2": f2,
        "private": f_private,
        "restricted": f_restricted,
    }

    return snapshot, posting, job_id, rev_hash, id_map


class TestJsonContextBuilder:
    def test_successful_build_with_all_invariants(self) -> None:
        snapshot, posting, job_id, rev_hash, id_map = create_builder_test_fixture()
        builder = JsonContextBuilder()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            requirements=["Python", "FastAPI"],
            instruction_text="Evaluate candidate against requirements.",
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=8192,
            output_reserve=512,
            safety_allowance=64,
        )

        bundle, error = builder.build(req)

        # Invariant: Exactly one non-null
        assert bundle is not None
        assert error is None

        # Strategy and versions
        assert bundle.strategy == ContextStrategy.JSON
        assert bundle.profile_version == snapshot.profile_version
        assert bundle.posting_revision == rev_hash
        assert bundle.purpose == "assessment"

        # Complete permitted evidence set
        eligible_ids = set(bundle.selected_fact_ids)
        assert id_map["f1"] in eligible_ids
        assert id_map["f2"] in eligible_ids
        assert id_map["private"] not in eligible_ids
        assert id_map["restricted"] not in eligible_ids
        assert len(bundle.ordered_facts) == 2

        # Null RAG metadata
        assert bundle.query_version is None
        assert bundle.index_version is None
        assert bundle.retrieval_settings is None

        # Budget accounting
        assert bundle.token_budget > 0
        assert bundle.estimated_tokens > 0
        assert bundle.budget_report is not None
        assert bundle.budget_report.fits is True
        assert bundle.content_fingerprint is not None

        # Structured mandatory context
        assert bundle.structured_mandatory is not None
        assert len(bundle.structured_mandatory.chronology) == 2

    def test_budget_overflow_returns_safe_error_without_partial_bundle(self) -> None:
        snapshot, posting, job_id, rev_hash, _ = create_builder_test_fixture()

        # Injected fake counter simulating oversized prompt
        fake_counter = FakeTokenCounter(
            fixed_total=5000,
            candidate_tokens=2000,
            instruction_tokens=1000,
            job_tokens=1500,
            framing_tokens=500,
        )
        builder = JsonContextBuilder(counter=fake_counter)

        # Window L = 4000, Demand = 5000 + 512 + 64 = 5576 -> Overflow 1576
        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=4000,
            output_reserve=512,
            safety_allowance=64,
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None
        assert error.category == ErrorCategory.CONTEXT_BUDGET
        assert error.recoverable is False
        assert "exceeds configured window by 1576 tokens" in error.message
        assert error.details["overflow"] == 1576

    def test_permission_conflict_returns_permission_error(self) -> None:
        snapshot, posting, job_id, rev_hash, id_map = create_builder_test_fixture()
        builder = JsonContextBuilder()

        # Explicitly requiring a restricted fact for assessment fails with permission conflict
        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=8192,
            explicit_mandatory_fact_ids=[id_map["restricted"]],
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None
        assert error.category == ErrorCategory.PERMISSION
        assert error.recoverable is False
        assert "restricted from purpose" in error.message

    def test_job_binding_hash_mismatch_returns_validation_error(self) -> None:
        snapshot, posting, job_id, _, _ = create_builder_test_fixture()
        builder = JsonContextBuilder()

        wrong_hash = "sha256:" + "d" * 64
        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=wrong_hash,
            job_content=posting,
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=8192,
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None
        assert error.category == ErrorCategory.VALIDATION
        assert "hash mismatch" in error.message

    def test_require_exact_measurement_rejection(self) -> None:
        snapshot, posting, job_id, rev_hash, _ = create_builder_test_fixture()
        # Default counter is ConservativeCharRatioEstimator (is_exact=False)
        builder = JsonContextBuilder()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=8192,
            require_exact_measurement=True,
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None
        assert error.category == ErrorCategory.UNSUPPORTED_INPUT
        assert "heuristic estimate" in error.message

    def test_reproducibility_across_repeated_builds(self) -> None:
        snapshot, posting, job_id, rev_hash, _ = create_builder_test_fixture()
        builder = JsonContextBuilder()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            requirements=["Python"],
            instruction_text="Instructions text.",
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=8192,
        )

        bundle1, _ = builder.build(req)
        bundle2, _ = builder.build(req)

        assert bundle1 is not None and bundle2 is not None
        assert bundle1.content_fingerprint == bundle2.content_fingerprint
        assert bundle1.selected_fact_ids == bundle2.selected_fact_ids
        assert bundle1.token_budget == bundle2.token_budget
        assert bundle1.estimated_tokens == bundle2.estimated_tokens
        assert bundle1.warnings == bundle2.warnings

