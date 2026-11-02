"""Contract boundary tests for CONTEXT-01 records, requests, reports, and C09 schemas."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.context.records import (
    JsonContextRequest,
    MeasurementResult,
    PreparedProfileContext,
    RenderedPrompt,
    WholePromptMeasurement,
)
from job_automation.context.settings import ContextSettings
from job_automation.contracts.context import (
    BudgetReport,
    ChronologyReference,
    ContextBundle,
    MandatoryFactReason,
    StructuredMandatoryContext,
)
from job_automation.contracts.enums import (
    ContextStrategy,
    EvidenceFactKind,
    WorkplaceType,
)
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import ContentHash, PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"


def create_sample_snapshot() -> ProfileSnapshot:
    cid = uuid.uuid4()
    f1 = uuid.uuid4()
    return ProfileSnapshot(
        candidate_id=cid,
        profile_version="v2026.1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate",
            approved_at=datetime.now(timezone.utc),
        ),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=[
            CandidateFact(
                fact_id=f1,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Software Engineer",
                provenance="test_attestation",
                allowed_uses=["assessment", "cv"],
            )
        ],
    )


def create_sample_posting() -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="12345"),
        normalizer_version="1.0",
        raw_reference="test_raw_ref",
        raw_content_hash="sha256:" + "a" * 64,
        company_name_hint="Acme Corp",
        title="Senior Python Engineer",
        description_clean="Clean job description text for testing.",
        workplace_type=WorkplaceType.HYBRID,
        source_url="https://example.com/jobs/12345",
        observed_at=datetime.now(timezone.utc),
    )


class TestContextContractBoundary:
    def test_json_context_request_positive(self) -> None:
        snapshot = create_sample_snapshot()
        posting = create_sample_posting()
        job_id = uuid.uuid4()

        req = JsonContextRequest(
            snapshot=snapshot,
            purpose="assessment",
            canonical_job_id=job_id,
            posting_revision="rev-1",
            job_content=posting,
            requirements=["Python", "SQL"],
            instruction_text="Evaluate candidate fit.",
            model_identifier="llama3:8b-instruct-q4_K_M",
            context_limit=4096,
            output_reserve=512,
            safety_allowance=64,
        )

        assert req.purpose == "assessment"
        assert req.context_limit == 4096
        assert req.output_reserve == 512
        assert req.safety_allowance == 64
        assert req.requirements == ["Python", "SQL"]

    def test_json_context_request_invalid_limits(self) -> None:
        snapshot = create_sample_snapshot()
        posting = create_sample_posting()
        job_id = uuid.uuid4()

        # Non-positive context limit
        with pytest.raises(ValidationError):
            JsonContextRequest(
                snapshot=snapshot,
                purpose="assessment",
                canonical_job_id=job_id,
                posting_revision="rev-1",
                job_content=posting,
                model_identifier="test-model",
                context_limit=0,
            )

        # Negative output reserve
        with pytest.raises(ValidationError):
            JsonContextRequest(
                snapshot=snapshot,
                purpose="assessment",
                canonical_job_id=job_id,
                posting_revision="rev-1",
                job_content=posting,
                model_identifier="test-model",
                context_limit=4096,
                output_reserve=-1,
            )

    def test_c09_context_bundle_round_trip_with_new_fields(self) -> None:
        cid = uuid.uuid4()
        f_id = uuid.uuid4()
        job_id = uuid.uuid4()

        report = BudgetReport(
            total_input_tokens=1500,
            candidate_tokens=600,
            instruction_tokens=200,
            job_tokens=600,
            framing_tokens=100,
            output_reserve=512,
            safety_allowance=64,
            effective_window=4096,
            candidate_allowance=2720,
            total_demand=2076,
            remaining_capacity=2020,
            overflow=0,
            fits=True,
            measurement_method="exact_tokenizer_v1",
            measurement_version="1.0",
            is_exact=True,
        )

        structured_mandatory = StructuredMandatoryContext(
            mandatory_fact_ids=[f_id],
            fact_reasons=[MandatoryFactReason(fact_id=f_id, reason="chronology_employment")],
            chronology=[
                ChronologyReference(
                    profile_version="v2026.1",
                    fact_id=f_id,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Software Engineer",
                    start_date=PrecisionDate(value="2020", precision="year"),
                    end_date=None,
                    reason="chronology_employment",
                )
            ],
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            eligibility_source="v2026.1#explicit_eligibility",
        )

        bundle = ContextBundle(
            strategy=ContextStrategy.JSON,
            profile_version="v2026.1",
            posting_revision="sha256:" + "0" * 64,
            ordered_facts=[],
            mandatory_context=["Work authorization: DE"],
            selected_fact_ids=[f_id],
            token_budget=2720,
            estimated_tokens=600,
            warnings=[],
            candidate_id=cid,
            purpose="assessment",
            inclusion_rule_version="v1",
            mandatory_policy_version="v1",
            builder_version="v1",
            serialization_version="v1",
            mandatory_fact_ids=[f_id],
            structured_mandatory=structured_mandatory,
            content_fingerprint="sha256:" + "f" * 64,
            budget_report=report,
        )

        dumped = bundle.model_dump(mode="json")
        reloaded = ContextBundle.model_validate(dumped)

        assert reloaded == bundle
        assert reloaded.candidate_id == cid
        assert reloaded.budget_report is not None
        assert reloaded.budget_report.is_exact is True
        assert reloaded.structured_mandatory is not None
        assert len(reloaded.structured_mandatory.chronology) == 1

    def test_legacy_c09_compatibility(self) -> None:
        """Supported legacy C09 records without new fields validate cleanly."""
        legacy_data = {
            "schema_version": "1.0",
            "strategy": "json",
            "profile_version": "v1",
            "posting_revision": "rev-123",
            "ordered_facts": [],
            "mandatory_context": ["Work auth: DE"],
            "selected_fact_ids": [str(uuid.uuid4())],
            "token_budget": 4000,
            "estimated_tokens": 1200,
            "warnings": [],
        }

        bundle = ContextBundle.model_validate(legacy_data)
        assert bundle.candidate_id is None
        assert bundle.budget_report is None
        assert bundle.structured_mandatory is None
        assert bundle.content_fingerprint is None

    def test_context_settings_defaults(self) -> None:
        settings = ContextSettings()
        assert settings.default_context_limit == 8192
        assert settings.default_output_reserve == 512
        assert settings.default_safety_allowance == 64
        assert settings.conservative_chars_per_token == 3.5
        assert settings.require_exact_measurement is False
