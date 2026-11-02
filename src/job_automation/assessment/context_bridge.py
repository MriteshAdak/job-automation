"""Context selector bridge for MATCH-02 (MATCH-02-S03).

Adapts AssessmentRequest and RequirementSet into ContextSelectionRequest,
invokes ContextSelectorV2, and validates returned ContextSelectionResult.
"""

from __future__ import annotations

from job_automation.assessment.llm_records import AssessmentRequest, RequirementSet
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import ContextSelectorV2


def select_assessment_context(
    context_selector: ContextSelectorV2,
    request: AssessmentRequest,
    requirement_set: RequirementSet,
    instruction_text: str = "",
    output_schema_text: str | None = None,
) -> tuple[ContextSelectionResult | None, ClassifiedError | None]:
    """Invoke ContextSelectorV2 with purpose='assessment' and exact version bindings.

    Enforces:
    - Same approved candidate snapshot for both JSON and RAG
    - Never silently switches strategy on error or budget overflow
    - Trace and admitted bundle validation
    """
    req_texts = [r.text for r in requirement_set.requirements]

    context_req = ContextSelectionRequest(
        strategy=request.context_strategy,
        snapshot=request.profile,
        purpose="assessment",
        canonical_job_id=request.canonical_job_id,
        posting_revision=request.posting_revision,
        job_content=request.posting,
        requirements=req_texts,
        instruction_text=instruction_text,
        output_schema_text=output_schema_text,
        model_identifier=request.model_identifier,
        context_limit=request.limits.context_limit,
        output_reserve=request.limits.output_reserve,
        safety_allowance=request.limits.safety_allowance,
        mandatory_policy_version=request.mandatory_policy_version,
        inclusion_rule_version=request.inclusion_rule_version,
        retrieval_settings=request.retrieval_settings,
        index_read_request=request.index_read_request,
        embedding_config=request.embedding_config,
        require_exact_measurement=request.require_exact_measurement,
    )

    result, err = context_selector.select_context(context_req)
    if err is not None:
        return None, err
    if result is None:
        return None, ClassifiedError.from_category(
            ErrorCategory.UNKNOWN,
            "ContextSelector returned neither a result nor a classified error",
        )

    # Validate returned bundle corresponds to the request
    bundle = result.bundle
    if bundle.strategy != request.context_strategy:
        return None, ClassifiedError.from_category(
            ErrorCategory.UNSUPPORTED_INPUT,
            f"Returned context bundle strategy '{bundle.strategy}' does not match requested '{request.context_strategy}'",
        )
    if bundle.profile_version != request.profile.profile_version:
        return None, ClassifiedError.from_category(
            ErrorCategory.UNSUPPORTED_INPUT,
            f"Returned bundle profile_version '{bundle.profile_version}' does not match request '{request.profile.profile_version}'",
        )
    if bundle.posting_revision != request.posting_revision:
        return None, ClassifiedError.from_category(
            ErrorCategory.UNSUPPORTED_INPUT,
            f"Returned bundle posting_revision '{bundle.posting_revision}' does not match request '{request.posting_revision}'",
        )

    return result, None

