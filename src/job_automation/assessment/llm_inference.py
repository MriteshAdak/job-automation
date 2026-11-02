"""Local model invocation harness for structured assessment proposals (MATCH-02-S05)."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError

from job_automation.assessment.llm_prompts import (
    ASSESSMENT_SYSTEM_INSTRUCTION,
    render_assessment_user_prompt,
)
from job_automation.assessment.llm_records import (
    AssessmentProposal,
    AssessmentRequest,
    RequirementSet,
)
from job_automation.context.selector_records import ContextSelectionResult
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.models import ModelCall, ModelResult
from job_automation.models.fingerprints import compute_generation_fingerprint
from job_automation.models.inputs import InMemoryInputResolver
from job_automation.models.records import BoundGenerationInput


def execute_assessment_inference(
    model_provider: ModelProvider,
    input_resolver: InMemoryInputResolver,
    request: AssessmentRequest,
    context_result: ContextSelectionResult,
    requirement_set: RequirementSet,
) -> tuple[AssessmentProposal | None, ModelCall | None, ModelResult | None, ClassifiedError | None]:
    """Execute structured assessment generation through LLM-01 ModelProvider under strict schemas."""
    user_prompt = render_assessment_user_prompt(
        rendered_prompt=context_result.rendered_prompt,
        requirement_set=requirement_set,
    )
    system_instruction = ASSESSMENT_SYSTEM_INSTRUCTION

    call_id = uuid.uuid4()

    bound_input = input_resolver.bind_generation(
        call_id=call_id,
        prompt=user_prompt,
        system_prompt=system_instruction,
        metadata={"schema_name": "assessment_proposal"},
    )

    call = ModelCall(
        call_id=call_id,
        operation_type="relevance_assessment",
        model_identifier=request.model_identifier,
        prompt_version=request.prompt_version,
        requested_schema="assessment_proposal",
        input_fingerprint=bound_input.input_fingerprint,
        context_limit=request.limits.context_limit,
    )

    result = model_provider.generate(call)

    if result.error is not None:
        return None, call, result, result.error

    if result.parsed_output is None:
        err = ClassifiedError.from_category(
            ErrorCategory.MODEL_OUTPUT,
            "Model returned null or unparseable structured output",
            details={"call_id": str(call_id)},
        )
        return None, call, result, err

    # Validate output against strict AssessmentProposal schema (forbidding extra fields, booleans in scores, etc.)
    try:
        proposal = AssessmentProposal.model_validate(result.parsed_output)
    except ValidationError as val_err:
        err = ClassifiedError.from_category(
            ErrorCategory.MODEL_OUTPUT,
            f"Model proposal violated strict output schema: {val_err}",
            details={"call_id": str(call_id), "validation_errors": str(val_err)},
        )
        return None, call, result, err

    return proposal, call, result, None
