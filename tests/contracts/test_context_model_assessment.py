"""Tests for C09 ContextBundle, C10 ModelCall/ModelResult, and C11 Assessment contracts."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from job_automation.contracts.assessment import (
    Assessment,
    LLMAssessmentMetadata,
    RuleOutcome,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMethod,
    ContextStrategy,
    HardCriterionResult,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage


class TestContextModelAssessment:
    def test_c09_context_bundle_json_and_rag(self) -> None:
        fact1_id = uuid.uuid4()
        fact2_id = uuid.uuid4()

        # JSON strategy bundle
        bundle_json = ContextBundle(
            strategy=ContextStrategy.JSON,
            profile_version="v2026.1",
            posting_revision="rev-sha256-abc",
            selected_fact_ids=[fact1_id, fact2_id],
            mandatory_context=["Work authorization: DE", "Total experience: 8 years"],
            token_budget=4000,
            estimated_tokens=1500,
        )
        assert bundle_json.strategy == ContextStrategy.JSON
        assert bundle_json.query_version is None

        # RAG strategy bundle
        bundle_rag = ContextBundle(
            strategy=ContextStrategy.RAG,
            profile_version="v2026.1",
            posting_revision="rev-sha256-abc",
            selected_fact_ids=[fact1_id],
            mandatory_context=["Work authorization: DE"],
            query_version="q_v1",
            index_version="idx_v1",
            retrieval_settings={"top_k": 5, "similarity_threshold": 0.75},
            token_budget=2000,
            estimated_tokens=800,
        )
        assert bundle_rag.strategy == ContextStrategy.RAG
        assert bundle_rag.query_version == "q_v1"

    def test_c10_model_call_and_result(self) -> None:
        call_id = uuid.uuid4()
        call = ModelCall(
            call_id=call_id,
            operation_type="relevance_assessment",
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v1",
            generation_settings={"temperature": 0.1},
            context_limit=8192,
            input_fingerprint="sha256:" + "0" * 64,
        )
        assert call.call_id == call_id

        # Model result with null token usage retains null, not zero
        result = ModelResult(
            call_id=call_id,
            model_identifier="llama3:8b-instruct-q4_K_M",
            output_text='{"disposition": "eligible", "score": 85}',
            parsed_output={"disposition": "eligible", "score": 85},
            latency_ms=1240.5,
            token_usage=None,
        )
        assert result.token_usage is None
        assert result.error is None

        # Model result with error
        err_result = ModelResult(
            call_id=call_id,
            model_identifier="llama3:8b-instruct-q4_K_M",
            output_text=None,
            error=ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Model service temporarily unavailable",
            ),
            latency_ms=50.0,
        )
        assert err_result.error is not None
        assert err_result.error.category == ErrorCategory.TRANSIENT_SERVICE

    def test_c11_rules_only_assessment_valid(self) -> None:
        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            posting_revision="rev-123",
            profile_version="v2026.1",
            policy_version="pol-1.0",
            assessment_method=AssessmentMethod.RULES,
            rule_outcomes=[
                RuleOutcome(
                    criterion_id="crit_auth",
                    criterion_name="Work Authorization",
                    result=HardCriterionResult.PASS,
                    reason="Candidate authorized in DE",
                ),
                RuleOutcome(
                    criterion_id="crit_salary",
                    criterion_name="Salary Threshold",
                    result=HardCriterionResult.UNKNOWN,
                    reason="Job posting does not state compensation",
                ),
            ],
            relevance_decision=AssessmentDisposition.REVIEW,
            summary_reason="Salary unstated in posting; requires human review",
            final_disposition=AssessmentDisposition.REVIEW,
            model_metadata=None,  # Null model metadata is valid for rules-only
        )
        assert assessment.assessment_method == AssessmentMethod.RULES
        assert assessment.model_metadata is None

    def test_c11_llm_assessment_requires_metadata(self) -> None:
        # LLM assessment without model_metadata must fail
        with pytest.raises(ValidationError, match="must provide model_metadata"):
            Assessment(
                assessment_id=uuid.uuid4(),
                canonical_job_id=uuid.uuid4(),
                posting_revision="rev-123",
                profile_version="v2026.1",
                policy_version="pol-1.0",
                assessment_method=AssessmentMethod.LLM,
                rule_outcomes=[],
                relevance_decision=AssessmentDisposition.ELIGIBLE,
                summary_reason="Strong fit for technical stack",
                final_disposition=AssessmentDisposition.ELIGIBLE,
                model_metadata=None,  # Missing!
            )

        # Valid with metadata
        meta = LLMAssessmentMetadata(
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v2",
            context_strategy=ContextStrategy.RAG,
            context_bundle_ref="bundle-hash-123",
        )
        assessment = Assessment(
            assessment_id=uuid.uuid4(),
            canonical_job_id=uuid.uuid4(),
            posting_revision="rev-123",
            profile_version="v2026.1",
            policy_version="pol-1.0",
            assessment_method=AssessmentMethod.LLM,
            rule_outcomes=[],
            relevance_decision=AssessmentDisposition.ELIGIBLE,
            relevance_score=85.0,
            score_scale="0-100",
            summary_reason="Strong fit for technical stack",
            final_disposition=AssessmentDisposition.ELIGIBLE,
            model_metadata=meta,
        )
        assert assessment.relevance_score == 85.0
        assert assessment.score_scale == "0-100"

    def test_c11_score_requires_documented_scale(self) -> None:
        meta = LLMAssessmentMetadata(
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v2",
            context_strategy=ContextStrategy.JSON,
        )
        with pytest.raises(ValidationError, match="score_scale must be documented"):
            Assessment(
                assessment_id=uuid.uuid4(),
                canonical_job_id=uuid.uuid4(),
                posting_revision="rev-123",
                profile_version="v2026.1",
                policy_version="pol-1.0",
                assessment_method=AssessmentMethod.LLM,
                relevance_decision=AssessmentDisposition.ELIGIBLE,
                relevance_score=85.0,
                score_scale=None,  # Missing!
                summary_reason="Fit evaluated",
                final_disposition=AssessmentDisposition.ELIGIBLE,
                model_metadata=meta,
            )

    def test_c11_hard_failure_precedence(self) -> None:
        meta = LLMAssessmentMetadata(
            model_identifier="llama3:8b-instruct-q4_K_M",
            prompt_version="assess_v2",
            context_strategy=ContextStrategy.JSON,
        )
        # Attempting to declare ELIGIBLE when a hard rule failed must fail validation
        with pytest.raises(ValidationError, match="confirmed hard criterion failure cannot be overridden"):
            Assessment(
                assessment_id=uuid.uuid4(),
                canonical_job_id=uuid.uuid4(),
                posting_revision="rev-123",
                profile_version="v2026.1",
                policy_version="pol-1.0",
                assessment_method=AssessmentMethod.LLM,
                rule_outcomes=[
                    RuleOutcome(
                        criterion_id="crit_location",
                        criterion_name="Location Check",
                        result=HardCriterionResult.FAIL,
                        reason="Job requires on-site presence in Tokyo",
                    )
                ],
                relevance_decision=AssessmentDisposition.ELIGIBLE,
                relevance_score=90.0,
                score_scale="0-100",
                summary_reason="High skills match despite location mismatch",
                final_disposition=AssessmentDisposition.ELIGIBLE,  # Invalid override!
                model_metadata=meta,
            )

