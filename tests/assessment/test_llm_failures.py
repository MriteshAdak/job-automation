"""Tests for recoverable failures, error classification, and pending envelopes (M02-07, M02-13)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from job_automation.assessment.llm_errors import make_pending_result
from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentProposal,
    AssessmentRequest,
    AssessmentRunResult,
    DeterministicDecisionTrace,
    FindingStatus,
    RequirementFindingProposal,
    RequirementItem,
    RequirementObligation,
    RequirementSet,
)
from job_automation.assessment.llm_service import LLMAssessmentService
from job_automation.context.selector_ports import ContextSelectionRequest, ContextSelectionResult
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    HardCriterionResult,
    WorkplaceType,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference, SourceSpan
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.models.inputs import BoundGenerationInput, InMemoryInputResolver
from tests.context.selector_test_helpers import create_selector_test_snapshot


def make_request_fixture():
    job_id = uuid.uuid4()
    posting_rev = "sha256:" + "7" * 64
    snapshot = create_selector_test_snapshot()

    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p-fail"),
        normalizer_version="1.0",
        raw_reference="test/ref.json",
        raw_content_hash=posting_rev,
        company_name_hint="Tech Corp",
        title="Python Engineer",
        description_clean="Python required",
        source_url="https://example.com/job/fail",
        workplace_type=WorkplaceType.REMOTE,
        observed_at=datetime.now(timezone.utc),
    )

    policy = SearchPolicy(policy_version="pol-1.0")

    baseline = Assessment(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        policy_version="pol-1.0",
        assessment_method=AssessmentMethod.RULES,
        relevance_decision=AssessmentDisposition.ELIGIBLE,
        final_disposition=AssessmentDisposition.ELIGIBLE,
        summary_reason="Baseline pass",
    )

    trace = DeterministicDecisionTrace()

    request = AssessmentRequest(
        assessment_id=uuid.uuid4(),
        canonical_job_id=job_id,
        posting_revision=posting_rev,
        posting=posting,
        profile=snapshot,
        policy=policy,
        context_strategy=ContextStrategy.JSON,
        deterministic_baseline=baseline,
        deterministic_trace=trace,
        limits=AssessmentLimits(),
    )

    return request, snapshot, posting, posting_rev


def test_assessment_run_result_mutual_exclusivity():
    """M02-01: AssessmentRunResult enforces mutual exclusivity between success and pending."""
    # 1. Success without assessment is invalid
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="success",
            assessment=None,
            input_fingerprint="sha256:fp",
        )

    # 2. Success with failed_stage is invalid
    request, snapshot, posting, posting_rev = make_request_fixture()
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="success",
            assessment=request.deterministic_baseline,
            failed_stage="inference",
            input_fingerprint="sha256:fp",
        )

    # 3. Pending with assessment is invalid
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="pending",
            assessment=request.deterministic_baseline,
            failed_stage="inference",
            input_fingerprint="sha256:fp",
        )

    # 4. Pending without failed_stage is invalid
    with pytest.raises(ValidationError):
        AssessmentRunResult(
            status="pending",
            assessment=None,
            input_fingerprint="sha256:fp",
        )


def test_make_pending_result_preserves_baseline_and_identity():
    """M02-07: Pending result helper preserves exact baseline and retryable flag."""
    request, _, _, _ = make_request_fixture()
    err = ClassifiedError.from_category(
        ErrorCategory.TRANSIENT_SERVICE,
        "Local model server connection refused",
    )

    pending = make_pending_result(
        failed_stage="inference",
        error=err,
        input_fingerprint="sha256:fp-123",
        deterministic_baseline=request.deterministic_baseline,
    )

    assert pending.status == "pending"
    assert pending.assessment is None
    assert pending.failed_stage == "inference"
    assert pending.retryable is True
    assert pending.input_fingerprint == "sha256:fp-123"
    assert pending.deterministic_baseline == request.deterministic_baseline


def test_service_returns_pending_on_model_outage():
    """M02-07: Model 503 / connection failure returns pending result with retryable=True."""
    request, snapshot, posting, posting_rev = make_request_fixture()

    mock_selector = MagicMock()
    bundle = ContextBundle(
        strategy=ContextStrategy.JSON,
        purpose="assessment",
        posting_revision=posting_rev,
        profile_version=snapshot.profile_version,
        selected_fact_ids=[snapshot.evidence_records[0].fact_id],
        token_budget=2000,
        estimated_tokens=100,
    )
    from job_automation.context.records import RenderedPrompt
    rendered = RenderedPrompt(
        full_prompt="prompt",
        job_text="Python required",
        candidate_json="{}",
    )
    ctx_res = ContextSelectionResult(
        bundle=bundle,
        rendered_prompt=rendered,
        construction_fingerprint="sha256:" + "c" * 64,
    )
    mock_selector.select_context.return_value = (ctx_res, None)

    mock_provider = MagicMock()
    outage_err = ClassifiedError.from_category(
        ErrorCategory.TRANSIENT_SERVICE,
        "Connection to llama.cpp refused on port 8080",
    )
    mock_provider.generate.return_value = ModelResult(
        call_id=uuid.uuid4(),
        model_identifier="test-model",
        error=outage_err,
        latency_ms=50,
    )

    service = LLMAssessmentService(
        context_selector=mock_selector,
        model_provider=mock_provider,
        input_resolver=InMemoryInputResolver(),
    )

    run_result = service.assess(request)

    assert run_result.status == "pending"
    assert run_result.assessment is None
    assert run_result.failed_stage == "inference"
    assert run_result.retryable is True
    assert run_result.deterministic_baseline == request.deterministic_baseline


def test_service_returns_pending_on_context_failure():
    """M02-07: Context selection failure returns pending result with failed_stage='context_selection'."""
    request, _, _, _ = make_request_fixture()

    mock_selector = MagicMock()
    ctx_err = ClassifiedError.from_category(
        ErrorCategory.CONTEXT_BUDGET,
        "Requested context exceeds model window limit",
    )
    mock_selector.select_context.return_value = (None, ctx_err)

    mock_provider = MagicMock()

    service = LLMAssessmentService(
        context_selector=mock_selector,
        model_provider=mock_provider,
        input_resolver=InMemoryInputResolver(),
    )

    run_result = service.assess(request)

    assert run_result.status == "pending"
    assert run_result.assessment is None
    assert run_result.failed_stage == "context_selection"
    assert run_result.retryable is False
    assert run_result.deterministic_baseline == request.deterministic_baseline
