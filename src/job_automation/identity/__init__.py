"""IDENTITY-01 — Company and Job Identity Resolution, Revisions, and Reversible Merges."""

from __future__ import annotations

from job_automation.identity.availability import AvailabilityService
from job_automation.identity.companies import (
    normalize_company_name,
    resolve_company_identity,
)
from job_automation.identity.errors import (
    ConflictError,
    IdentityError,
    InvalidOperationError,
    MergeError,
    ReversalError,
    ReviewCaseNotFoundError,
)
from job_automation.identity.hashing import (
    compute_revision_content_hash,
    compute_revision_content_projection,
)
from job_automation.identity.matching import (
    calculate_text_similarity,
    extract_requisition_hint,
    find_review_candidates,
    find_strong_job_match,
)
from job_automation.identity.merges import (
    execute_merge,
    execute_reversal,
)
from job_automation.identity.models import (
    CompanyIdentity,
    IdentityResolutionResult,
    MatchOutcome,
    MergeOperation,
    ReversalOperation,
    ReviewCase,
)
from job_automation.identity.review import (
    create_review_case,
    decide_review_case,
    list_review_cases,
)
from job_automation.identity.revisions import (
    create_posting_revision,
    select_current_revision,
    update_revision_observation,
)
from job_automation.identity.service import IdentityService
from job_automation.identity.urls import (
    are_urls_equivalent,
    is_job_specific_url,
    validate_url,
)

__all__ = [
    "AvailabilityService",
    "CompanyIdentity",
    "ConflictError",
    "IdentityError",
    "IdentityResolutionResult",
    "IdentityService",
    "InvalidOperationError",
    "MatchOutcome",
    "MergeError",
    "MergeOperation",
    "ReversalError",
    "ReversalOperation",
    "ReviewCase",
    "ReviewCaseNotFoundError",
    "are_urls_equivalent",
    "calculate_text_similarity",
    "compute_revision_content_hash",
    "compute_revision_content_projection",
    "create_posting_revision",
    "create_review_case",
    "decide_review_case",
    "execute_merge",
    "execute_reversal",
    "extract_requisition_hint",
    "find_review_candidates",
    "find_strong_job_match",
    "is_job_specific_url",
    "list_review_cases",
    "normalize_company_name",
    "resolve_company_identity",
    "select_current_revision",
    "update_revision_observation",
    "validate_url",
]

