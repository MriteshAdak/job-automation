"""Missing-information precedence resolution and validation."""

from __future__ import annotations

from typing import Any, Literal

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import HardCriterion, SearchPolicy
from job_automation.policy.fields import SUPPORTED_TARGET_NAMES
from job_automation.policy.models import EffectiveMissingAction

ALLOWED_MISSING_ACTIONS: frozenset[str] = frozenset({"pass", "fail", "unknown"})


def resolve_effective_missing_actions(
    hard_criteria: list[HardCriterion],
    missing_behavior: dict[str, Literal["pass", "fail", "unknown"]],
    explicit_on_missing: dict[str, bool],
) -> tuple[dict[str, EffectiveMissingAction], list[ValidationIssue]]:
    """Resolve effective missing action for each hard criterion following D03 precedence:
    
    Precedence:
    1. Explicit rule-level on_missing in input JSON -> source='explicit_rule'
    2. Field-level setting in missing_information_behavior -> source='field_default'
    3. Global default 'unknown' -> source='global_default'
    """
    issues: list[ValidationIssue] = []
    effective_actions: dict[str, EffectiveMissingAction] = {}

    # Validate missing_information_behavior keys and values
    for field_name, action in missing_behavior.items():
        if action not in ALLOWED_MISSING_ACTIONS:
            issues.append(
                ValidationIssue(
                    field_path=f"missing_information_behavior['{field_name}']",
                    code="invalid_missing_action",
                    message=f"Missing action must be one of {sorted(ALLOWED_MISSING_ACTIONS)}, got '{action}'",
                    severity="error",
                )
            )
        if field_name not in SUPPORTED_TARGET_NAMES:
            issues.append(
                ValidationIssue(
                    field_path=f"missing_information_behavior['{field_name}']",
                    code="unknown_missing_field",
                    message=(
                        f"Field '{field_name}' in missing_information_behavior is not a supported target. "
                        f"Supported targets: {sorted(SUPPORTED_TARGET_NAMES)}"
                    ),
                    severity="warning",
                )
            )

    # Materialize effective actions for each criterion
    for crit in hard_criteria:
        is_explicit = explicit_on_missing.get(crit.criterion_id, False)
        if is_explicit:
            effective_actions[crit.criterion_id] = EffectiveMissingAction(
                action=crit.on_missing,
                source="explicit_rule",
            )
        elif crit.field in missing_behavior:
            effective_actions[crit.criterion_id] = EffectiveMissingAction(
                action=missing_behavior[crit.field],
                source="field_default",
            )
        else:
            effective_actions[crit.criterion_id] = EffectiveMissingAction(
                action="unknown",
                source="global_default",
            )

    return effective_actions, issues

