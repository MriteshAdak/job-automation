"""Tests for model-assisted requirement extraction (M02-02, M02-03, M02-09)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.assessment.llm_records import (
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.assessment.requirements import prepare_requirements
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.evidence import JobEvidenceReference, SourceSpan
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.models.inputs import InMemoryInputResolver
from tests.fakes.fake_services import FakeModelProvider


class ScriptedExtractionProvider:
    """Scripted model provider returning specific extraction payloads."""

    def __init__(self, response_payload: dict | None = None, should_fail: bool = False) -> None:
        self.response_payload = response_payload
        self.should_fail = should_fail
        self.last_call: ModelCall | None = None
        self.last_prompt: str | None = None

    def generate(self, call: ModelCall) -> ModelResult:
        self.last_call = call
        if self.should_fail:
            return ModelResult(
                call_id=call.call_id,
                model_identifier=call.model_identifier,
                error=ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_SERVICE,
                    "Extraction model service 503",
                ),
                latency_ms=10.0,
            )

        return ModelResult(
            call_id=call.call_id,
            model_identifier=call.model_identifier,
            output_text="{}",
            parsed_output=self.response_payload or {"requirements": []},
            latency_ms=50.0,
        )

    def embed(self, texts: list[str], model: str):
        return None, None


def test_m02_02_extraction_receives_job_text_only():
    """Requirement extraction receives ONLY job text and ZERO candidate facts in its prompt."""
    desc = "We need a Senior Go Developer with Kubernetes experience."
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p1"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "a" * 64,
        company_name_hint="Cloud Corp",
        title="Go Developer",
        description_clean=desc,
        source_url="https://example.com/job/1",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "a" * 64

    resolver = InMemoryInputResolver()
    provider = ScriptedExtractionProvider(
        response_payload={
            "requirements": [
                {
                    "text": "Go Developer with Kubernetes experience",
                    "quotation": "Senior Go Developer with Kubernetes experience",
                    "start": 11,
                    "end": 56,
                    "obligation": "required",
                    "category": "skill",
                }
            ]
        }
    )

    req_set = prepare_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
        mode="llm",
        model_provider=provider,
        input_resolver=resolver,
    )

    assert provider.last_call is not None
    # Inspect bound input in resolver
    bound_input = resolver.resolve_generation_input(provider.last_call.call_id)
    assert bound_input is not None
    assert "candidate" not in bound_input.prompt.lower()
    assert "facts" not in bound_input.prompt.lower()
    assert desc in bound_input.prompt
    assert len(req_set.requirements) == 1
    assert req_set.requirements[0].obligation == RequirementObligation.REQUIRED


def test_m02_03_flags_unsupported_requirement_extraction():
    """Detects unsupported threshold/years claim not supported by cited quotation."""
    desc = "We are seeking experience in Python development."
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p2"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "b" * 64,
        company_name_hint="Acme Corp",
        title="Python Dev",
        description_clean=desc,
        source_url="https://example.com/job/2",
        workplace_type=WorkplaceType.ONSITE,
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "b" * 64

    # Model hallucinates "5 years" when the quote only says "experience in Python development"
    resolver = InMemoryInputResolver()
    provider = ScriptedExtractionProvider(
        response_payload={
            "requirements": [
                {
                    "text": "5 years of Python experience required",
                    "quotation": "experience in Python development",
                    "start": 15,
                    "end": 47,
                    "obligation": "required",
                    "category": "skill",
                    "threshold": "5",  # Unsupported! Quote doesn't say 5 years
                    "unit": "years",
                }
            ]
        }
    )

    req_set = prepare_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
        mode="llm",
        model_provider=provider,
        input_resolver=resolver,
    )

    unsupported_issues = [iss for iss in req_set.issues if iss.code == "unsupported_requirement_extraction"]
    assert len(unsupported_issues) >= 1
    assert "threshold '5'" in unsupported_issues[0].message


def test_m02_02_extraction_failure_falls_back_to_deterministic():
    """When LLM extraction fails with a service error, falls back to deterministic extraction with visible issue."""
    desc = "Requirements:\n- 3+ years experience with PostgreSQL"
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p3"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "c" * 64,
        company_name_hint="DB Corp",
        title="Database Engineer",
        description_clean=desc,
        source_url="https://example.com/job/3",
        workplace_type=WorkplaceType.ONSITE,
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "c" * 64

    resolver = InMemoryInputResolver()
    provider = ScriptedExtractionProvider(should_fail=True)

    req_set = prepare_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
        mode="llm",
        model_provider=provider,
        input_resolver=resolver,
    )

    # Fallback to deterministic extraction succeeded
    assert len(req_set.requirements) >= 1
    assert any("PostgreSQL" in r.text for r in req_set.requirements)
    # Failure is recorded in issues
    fail_issues = [iss for iss in req_set.issues if iss.code == "extraction_call_failed"]
    assert len(fail_issues) == 1

