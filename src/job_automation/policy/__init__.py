"""POLICY-01 — Search policy and vocabulary validation package."""

from __future__ import annotations

from job_automation.policy.conflicts import detect_policy_conflicts
from job_automation.policy.criteria import validate_criteria_and_preferences
from job_automation.policy.fields import (
    SUPPORTED_TARGET_NAMES,
    TARGET_CATALOG,
    TargetDefinition,
)
from job_automation.policy.fingerprint import (
    build_canonical_payload,
    compute_policy_fingerprint,
)
from job_automation.policy.loader import load_policy_dict
from job_automation.policy.missing import resolve_effective_missing_actions
from job_automation.policy.models import (
    CANONICALIZATION_VERSION,
    NORMALIZATION_VERSION,
    POLICY_SCHEMA_VERSION,
    POLICY_SEMANTICS_VERSION,
    EffectiveMissingAction,
    EffectivePolicy,
    PolicyMetadata,
    PolicyValidationResult,
    SalaryOperand,
)
from job_automation.policy.service import PolicyService
from job_automation.policy.validation import validate_policy_dict
from job_automation.policy.vocabulary import (
    NormalizedVocabulary,
    VocabularyGroup,
    normalize_display,
    normalize_lookup,
    validate_vocabulary,
)

__all__ = [
    "CANONICALIZATION_VERSION",
    "NORMALIZATION_VERSION",
    "POLICY_SCHEMA_VERSION",
    "POLICY_SEMANTICS_VERSION",
    "EffectiveMissingAction",
    "EffectivePolicy",
    "NormalizedVocabulary",
    "PolicyMetadata",
    "PolicyService",
    "PolicyValidationResult",
    "SalaryOperand",
    "SUPPORTED_TARGET_NAMES",
    "TARGET_CATALOG",
    "TargetDefinition",
    "VocabularyGroup",
    "build_canonical_payload",
    "compute_policy_fingerprint",
    "detect_policy_conflicts",
    "load_policy_dict",
    "normalize_display",
    "normalize_lookup",
    "resolve_effective_missing_actions",
    "validate_criteria_and_preferences",
    "validate_policy_dict",
    "validate_vocabulary",
]

