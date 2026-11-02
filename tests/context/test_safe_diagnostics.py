"""Tests ensuring safe diagnostics and prevention of sensitive claim text leaks in errors and warnings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from job_automation.context.json_builder import JsonContextBuilder
from job_automation.context.records import JsonContextRequest
from job_automation.contracts.enums import EvidenceFactKind, WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.fakes.context_measurement import FakeTokenCounter

CONFIDENTIAL_CLAIM = "TOP_SECRET_INTERNAL_CREDENTIALS_AND_METRICS_xyz123"
PROPRIETARY_JOB_SECRET = "INTERNAL_CONFIDENTIAL_SALARY_BAND_AND_REQUISITION_456"


def create_sentinel_fixture() -> tuple[ProfileSnapshot, NormalizedPosting, uuid.UUID, str, uuid.UUID]:
    cid = uuid.uuid4()
    f_private = uuid.uuid4()
    f_allowed = uuid.uuid4()
    job_id = uuid.uuid4()
    rev_hash = "sha256:" + "e" * 64
    now = datetime.now(timezone.utc)

    facts = [
        CandidateFact(
            fact_id=f_private,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Private Position",
            claims=[CONFIDENTIAL_CLAIM],
            provenance="secret_contract.pdf",
            allowed_uses=[],  # Private
        ),
        CandidateFact(
            fact_id=f_allowed,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Normal Position",
            claims=["Public claim text"],
            provenance="normal_contract.pdf",
            allowed_uses=["assessment", "cv"],
        ),
    ]

    snapshot = ProfileSnapshot(
        candidate_id=cid,
        profile_version="v1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate",
            approved_at=now,
        ),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=facts,
    )

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="102"),
        normalizer_version="1.0",
        raw_reference="ref_102",
        raw_content_hash=rev_hash,
        company_name_hint="Company AG",
        title="Developer",
        description_clean=f"Normal job text with {PROPRIETARY_JOB_SECRET}",
        workplace_type=WorkplaceType.REMOTE,
        source_url="https://example.com/job/102",
        observed_at=now,
    )

    return snapshot, posting, job_id, rev_hash, f_private


class TestSafeDiagnostics:
    def test_budget_overflow_error_does_not_leak_secrets(self) -> None:
        snapshot, posting, job_id, rev_hash, _ = create_sentinel_fixture()

        # Overflow condition
        fake_counter = FakeTokenCounter(fixed_total=5000)
        builder = JsonContextBuilder(counter=fake_counter)

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="test-model",
            context_limit=4000,
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None

        # Verify neither confidential candidate text nor proprietary job secret appears in error
        error_str = f"{error.message} {error.details}"
        assert CONFIDENTIAL_CLAIM not in error_str
        assert PROPRIETARY_JOB_SECRET not in error_str

    def test_permission_error_does_not_leak_secrets(self) -> None:
        snapshot, posting, job_id, rev_hash, f_private = create_sentinel_fixture()
        builder = JsonContextBuilder()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="test-model",
            context_limit=8192,
            explicit_mandatory_fact_ids=[f_private],
        )

        bundle, error = builder.build(req)

        assert bundle is None
        assert error is not None

        error_str = f"{error.message} {error.details}"
        assert CONFIDENTIAL_CLAIM not in error_str
        assert PROPRIETARY_JOB_SECRET not in error_str

    def test_successful_bundle_warnings_do_not_leak_secrets(self) -> None:
        snapshot, posting, job_id, rev_hash, _ = create_sentinel_fixture()
        builder = JsonContextBuilder()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision=rev_hash,
            job_content=posting,
            model_identifier="test-model",
            context_limit=8192,
        )

        bundle, error = builder.build(req)

        assert bundle is not None
        assert error is None

        # Check bundle warnings
        warnings_str = " ".join(bundle.warnings)
        assert CONFIDENTIAL_CLAIM not in warnings_str

