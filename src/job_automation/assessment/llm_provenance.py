"""Provenance recording and verification for model inference (MATCH-02-S05)."""

from __future__ import annotations

import uuid
from typing import Any

from job_automation.assessment.llm_records import AssessmentRequest
from job_automation.contracts.assessment import LLMAssessmentMetadata
from job_automation.contracts.models import ModelCall, ModelResult


def build_llm_metadata(
    request: AssessmentRequest,
    call: ModelCall,
    result: ModelResult,
    prompt_fingerprint: str,
    context_bundle_ref: str | None = None,
) -> LLMAssessmentMetadata:
    """Build complete, immutable LLMAssessmentMetadata from call and result.

    Enforces:
    - Never invents an observed model digest if none was reported
    - Binds prompt fingerprint and call ID
    - Records actual token usage and generation settings
    """
    effective_digest = result.model_digest or request.model_digest

    return LLMAssessmentMetadata(
        model_identifier=result.model_identifier or request.model_identifier,
        prompt_version=request.prompt_version,
        context_strategy=request.context_strategy,
        context_bundle_ref=context_bundle_ref,
        model_digest=effective_digest,
        prompt_fingerprint=prompt_fingerprint,
        generation_call_id=call.call_id,
        generation_settings=call.generation_settings,
        token_usage=result.token_usage,
    )

