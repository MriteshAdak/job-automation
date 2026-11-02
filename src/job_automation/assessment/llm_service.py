"""Public LLM Assessment Service implementing AssessorV2 and legacy Assessor adapter (MATCH-02)."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.assessment.context_bridge import select_assessment_context
from job_automation.assessment.errors import AssessmentInputError
from job_automation.assessment.finding_validation import validate_proposal_findings
from job_automation.assessment.llm_composition import compose_llm_assessment
from job_automation.assessment.llm_errors import make_pending_result
from job_automation.assessment.llm_inference import execute_assessment_inference
from job_automation.assessment.llm_inputs import compute_assessment_input_fingerprint
from job_automation.assessment.llm_ports import AssessorV2Port
from job_automation.assessment.llm_provenance import build_llm_metadata
from job_automation.assessment.llm_records import (
    AssessmentRequest,
    AssessmentRunResult,
    RequirementSet,
)
from job_automation.assessment.requirements import prepare_requirements
from job_automation.contracts.assessment import Assessment, RuleOutcome
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import (
    Assessor,
    AssessorV2,
    ContextSelectorV2,
    ModelProvider,
)
from job_automation.models.inputs import InMemoryInputResolver


class LLMAssessmentService(AssessorV2):
    """Production model-assisted assessment service implementing AssessorV2 boundary."""

    def __init__(
        self,
        context_selector: ContextSelectorV2,
        model_provider: ModelProvider,
        input_resolver: InMemoryInputResolver | None = None,
    ) -> None:
        self.context_selector = context_selector
        self.model_provider = model_provider
        self.input_resolver = (
            input_resolver if input_resolver is not None else InMemoryInputResolver()
        )

    def assess(self, request: AssessmentRequest) -> AssessmentRunResult:
        """Perform full model-assisted assessment combining rules, context, and inference."""
        # 1. Pre-retrieval requirement preparation
        req_set = prepare_requirements(
            posting=request.posting,
            posting_revision=request.posting_revision,
            canonical_job_id=request.canonical_job_id,
            policy=request.policy if hasattr(request.policy, "policy_version") else None,
            max_requirements=request.limits.max_requirements,
            mode=request.extractor_mode,
            model_provider=self.model_provider,
            input_resolver=self.input_resolver,
            model_identifier=request.model_identifier,
        )

        input_fingerprint = compute_assessment_input_fingerprint(request, req_set)

        # 2. Context selection via shared selector
        context_res, ctx_err = select_assessment_context(
            context_selector=self.context_selector,
            request=request,
            requirement_set=req_set,
        )
        if ctx_err is not None:
            return make_pending_result(
                failed_stage="context_selection",
                error=ctx_err,
                input_fingerprint=input_fingerprint,
                deterministic_baseline=request.deterministic_baseline,
                retryable=getattr(ctx_err, "recoverable", getattr(ctx_err, "retryable", False)),
            )
        assert context_res is not None

        # 3. Model inference under strict schema
        proposal, call, model_res, inf_err = execute_assessment_inference(
            model_provider=self.model_provider,
            input_resolver=self.input_resolver,
            request=request,
            context_result=context_res,
            requirement_set=req_set,
        )
        if inf_err is not None:
            return make_pending_result(
                failed_stage="inference",
                error=inf_err,
                input_fingerprint=input_fingerprint,
                deterministic_baseline=request.deterministic_baseline,
                retryable=getattr(inf_err, "recoverable", getattr(inf_err, "retryable", False)),
            )
        assert proposal is not None
        assert call is not None
        assert model_res is not None

        # 4. Reference & finding validation
        validated_findings, validation_issues = validate_proposal_findings(
            proposal=proposal,
            requirement_set=req_set,
            profile=request.profile,
            posting=request.posting,
            posting_revision=request.posting_revision,
            bundle=context_res.bundle,
        )

        # Check for fatal reference issues
        fatal_ref_issues = [
            iss
            for iss in validation_issues
            if iss.code in ("out_of_bounds_span", "unselected_fact_reference", "unknown_candidate_fact_id", "quotation_not_found")
        ]
        if fatal_ref_issues:
            first_iss = fatal_ref_issues[0]
            fatal_err = ClassifiedError.from_category(
                ErrorCategory.MODEL_OUTPUT,
                f"Model proposal cited invalid or unadmitted evidence: {first_iss.message}",
                details={"issue_code": first_iss.code, "field_path": first_iss.field_path},
            )
            return make_pending_result(
                failed_stage="validation",
                error=fatal_err,
                input_fingerprint=input_fingerprint,
                deterministic_baseline=request.deterministic_baseline,
                validation_issues=validation_issues,
                retryable=False,
            )

        # 5. Build LLM provenance metadata
        llm_meta = build_llm_metadata(
            request=request,
            call=call,
            result=model_res,
            prompt_fingerprint=call.input_fingerprint,
            context_bundle_ref=context_res.construction_fingerprint,
        )

        # 6. Compose C11 assessment with deterministic authority
        assessment = compose_llm_assessment(
            request=request,
            requirement_set=req_set,
            validated_findings=validated_findings,
            validation_issues=validation_issues,
            proposal=proposal,
            llm_metadata=llm_meta,
            input_fingerprint=input_fingerprint,
        )

        return AssessmentRunResult(
            status="success",
            assessment=assessment,
            input_fingerprint=input_fingerprint,
            audit_references={
                "call_id": str(call.call_id),
                "prompt_fingerprint": call.input_fingerprint,
                "context_fingerprint": context_res.construction_fingerprint,
            },
        )


class LegacyAssessorAdapter(Assessor):
    """Adapter implementing legacy Boundary 7 Assessor protocol."""

    def __init__(self, v2_service: AssessorV2) -> None:
        self.v2_service = v2_service

    def assess(
        self,
        rule_outcomes: list[RuleOutcome],
        revision: PostingRevision,
        context: ContextBundle,
    ) -> Assessment:
        """Execute legacy assess interface. Fails visibly if complete binding is not provided."""
        raise AssessmentInputError(
            "Legacy Assessor.assess lacks explicit policy/profile/posting bindings. "
            "Use AssessorV2 with AssessmentRequest."
        )
