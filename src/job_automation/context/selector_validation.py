"""Validation for context selection requests according to shared contracts."""

from __future__ import annotations

from job_automation.context.binding import DefaultJobBindingValidator
from job_automation.context.errors import (
    ContextBudgetOverflowError,
    ContextUnsupportedError,
    ContextValidationError,
    JobBindingError,
)
from job_automation.context.ports import JobBindingPort
from job_automation.context.selector_records import ContextSelectionRequest

SUPPORTED_PURPOSES = {"assessment", "cv", "cover_letter"}
SUPPORTED_POLICY_VERSIONS = {"v1"}
SUPPORTED_INCLUSION_VERSIONS = {"v1"}
SUPPORTED_BUILDER_VERSIONS = {"v1"}
SUPPORTED_SERIALIZATION_VERSIONS = {"v1"}


def validate_context_selection_request(
    request: ContextSelectionRequest,
    job_binding_validator: JobBindingPort | None = None,
) -> None:
    """Validate approved profile snapshot, purpose, versions, and job content correspondence."""
    # 1. Validate approval metadata
    if not request.snapshot.approval_metadata.is_approved:
        raise ContextValidationError(
            "Candidate profile snapshot must have explicit human approval (is_approved=True)",
            field_path="snapshot.approval_metadata.is_approved",
        )

    # 2. Validate supported purpose
    if request.purpose not in SUPPORTED_PURPOSES:
        raise ContextUnsupportedError(
            f"Unsupported context purpose '{request.purpose}'. Supported purposes: {sorted(SUPPORTED_PURPOSES)}",
            field_path="purpose",
        )

    # 3. Validate supported versions
    if request.mandatory_policy_version not in SUPPORTED_POLICY_VERSIONS:
        raise ContextUnsupportedError(
            f"Unsupported mandatory policy version '{request.mandatory_policy_version}'",
            field_path="mandatory_policy_version",
        )
    if request.inclusion_rule_version not in SUPPORTED_INCLUSION_VERSIONS:
        raise ContextUnsupportedError(
            f"Unsupported inclusion rule version '{request.inclusion_rule_version}'",
            field_path="inclusion_rule_version",
        )
    if request.builder_version not in SUPPORTED_BUILDER_VERSIONS:
        raise ContextUnsupportedError(
            f"Unsupported builder version '{request.builder_version}'",
            field_path="builder_version",
        )
    if request.serialization_version not in SUPPORTED_SERIALIZATION_VERSIONS:
        raise ContextUnsupportedError(
            f"Unsupported serialization version '{request.serialization_version}'",
            field_path="serialization_version",
        )

    # 4. Validate job binding correspondence
    validator = job_binding_validator or DefaultJobBindingValidator()
    try:
        validator.validate_binding(
            canonical_job_id=request.canonical_job_id,
            posting_revision=request.posting_revision,
            posting=request.job_content,
        )
    except JobBindingError:
        raise
    except Exception as exc:
        raise JobBindingError(
            f"Job binding validation failed: {exc}",
            field_path="posting_revision",
        ) from exc

    # 5. Validate context limit and reserves
    effective_candidate_window = request.context_limit - (
        request.output_reserve + request.safety_allowance
    )
    if effective_candidate_window <= 0:
        raise ContextBudgetOverflowError(
            f"Context limit ({request.context_limit}) exhausted by output reserve "
            f"({request.output_reserve}) and safety allowance ({request.safety_allowance})",
            field_path="context_limit",
            details={
                "context_limit": request.context_limit,
                "output_reserve": request.output_reserve,
                "safety_allowance": request.safety_allowance,
            },
        )
