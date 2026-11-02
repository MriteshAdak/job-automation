"""Comprehensive policy validation coordinating schema, vocabulary, criteria, missing rules, and conflicts."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import ValidationError

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.policy.conflicts import detect_policy_conflicts
from job_automation.policy.criteria import validate_criteria_and_preferences
from job_automation.policy.fingerprint import compute_policy_fingerprint
from job_automation.policy.missing import resolve_effective_missing_actions
from job_automation.policy.models import (
    POLICY_SCHEMA_VERSION,
    EffectivePolicy,
    PolicyMetadata,
    PolicyValidationResult,
)
from job_automation.policy.vocabulary import validate_vocabulary


def validate_policy_dict(
    raw_data: dict[str, Any],
    explicit_on_missing: dict[str, bool] | None = None,
) -> PolicyValidationResult:
    """Validate a parsed policy dictionary through all validation layers."""
    if explicit_on_missing is None:
        explicit_on_missing = {}
        hard_raw = raw_data.get("hard_criteria")
        if isinstance(hard_raw, list):
            for idx, item in enumerate(hard_raw):
                if isinstance(item, dict):
                    cid = item.get("criterion_id") or f"index_{idx}"
                    explicit_on_missing[cid] = "on_missing" in item

    # 0. Check schema_version
    schema_ver = raw_data.get("schema_version")
    if schema_ver is not None and schema_ver != POLICY_SCHEMA_VERSION:
        return PolicyValidationResult(
            is_valid=False,
            effective_policy=None,
            fingerprint=None,
            issues=[
                ValidationIssue(
                    field_path="schema_version",
                    code="unsupported_schema_version",
                    message=(
                        f"Unsupported policy schema_version '{schema_ver}'; "
                        f"only version '{POLICY_SCHEMA_VERSION}' is supported"
                    ),
                    severity="error",
                )
            ],
        )

    # 1. Structural C02 model validation via Pydantic
    try:
        policy = SearchPolicy.model_validate(raw_data)
    except ValidationError as exc:
        issues: list[ValidationIssue] = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            safe_msg = err["msg"]
            if "SECRET" in safe_msg:
                safe_msg = "Invalid value"
            issues.append(
                ValidationIssue(
                    field_path=loc,
                    code="schema_violation",
                    message=safe_msg,
                    severity="error",
                )
            )
        return PolicyValidationResult(
            is_valid=False,
            effective_policy=None,
            fingerprint=None,
            issues=issues,
        )

    authored_version = policy.policy_version

    # 2. Vocabulary validation (German/English aliases, collision & chain detection)
    vocab, vocab_issues = validate_vocabulary(policy.role_aliases, policy.skill_aliases)

    # 3. Criteria, preferences, exclusions, relevance, and strategy validation
    criteria_issues = validate_criteria_and_preferences(policy)

    # 4. Missing-information precedence resolution
    effective_missing, missing_issues = resolve_effective_missing_actions(
        policy.hard_criteria,
        policy.missing_information_behavior,
        explicit_on_missing,
    )

    # 5. Cross-policy bounded conflict detection
    conflict_issues = detect_policy_conflicts(policy, vocab)

    # Aggregate and sort all issues
    all_issues = vocab_issues + criteria_issues + missing_issues + conflict_issues
    all_issues.sort(key=lambda i: (i.field_path, i.code, i.severity))

    has_errors = any(i.severity == "error" for i in all_issues)
    if has_errors:
        return PolicyValidationResult(
            is_valid=False,
            effective_policy=None,
            fingerprint=None,
            issues=all_issues,
        )

    # 6. Compute deterministic fingerprint
    fingerprint, canonical_bytes = compute_policy_fingerprint(policy, effective_missing, vocab)

    # 7. Construct effective C02 model bound to computed fingerprint
    # Materialize effective on_missing in criteria
    materialized_criteria: list[HardCriterion] = []
    for crit in policy.hard_criteria:
        action = effective_missing[crit.criterion_id].action if crit.criterion_id in effective_missing else crit.on_missing
        crit_dump = crit.model_dump()
        crit_dump["on_missing"] = action
        materialized_criteria.append(HardCriterion.model_validate(crit_dump))

    effective_policy_dump = policy.model_dump()
    effective_policy_dump["policy_version"] = fingerprint
    effective_policy_dump["hard_criteria"] = [c.model_dump() for c in materialized_criteria]
    effective_search_policy = SearchPolicy.model_validate(effective_policy_dump)

    metadata = PolicyMetadata(
        authored_version=authored_version,
        effective_version=fingerprint,
    )

    effective = EffectivePolicy(
        policy=effective_search_policy,
        metadata=metadata,
        effective_missing_actions=effective_missing,
        canonical_bytes=canonical_bytes,
    )

    return PolicyValidationResult(
        is_valid=True,
        effective_policy=effective,
        fingerprint=fingerprint,
        issues=all_issues,
    )
