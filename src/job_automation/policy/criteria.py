"""Validation of hard criteria, preferences, exclusions, and relevance config."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    RelevanceConfig,
    SearchPolicy,
)
from job_automation.policy.fields import (
    TARGET_CATALOG,
    is_candidate_field,
    is_skills_target,
)
from job_automation.policy.models import SalaryOperand

# Regex patterns that indicate unwanted regex syntax in literal exclusions
REGEX_CHARACTERS = re.compile(r"[\^\$\*\+\?\{\}\[\]\\\|\(\)]")


def _validate_salary_operand(value: Any, path: str) -> tuple[SalaryOperand | None, list[ValidationIssue]]:
    """Validate that a compensation operand has explicit amount, currency, and period."""
    issues: list[ValidationIssue] = []
    if isinstance(value, (int, float, Decimal)):
        issues.append(
            ValidationIssue(
                field_path=path,
                code="ambiguous_salary_units",
                message=(
                    f"Bare numeric salary '{value}' is ambiguous. "
                    "Compensation criteria require an explicit operand with 'amount', 'currency' (e.g. 'EUR'), "
                    "and 'period' (e.g. 'yearly', 'monthly')."
                ),
                severity="error",
            )
        )
        return None, issues

    if not isinstance(value, dict):
        issues.append(
            ValidationIssue(
                field_path=path,
                code="invalid_operand_type",
                message=f"Expected a structured salary object with amount, currency, and period, got {type(value).__name__}",
                severity="error",
            )
        )
        return None, issues

    try:
        operand = SalaryOperand.model_validate(value)
        return operand, issues
    except Exception as exc:
        issues.append(
            ValidationIssue(
                field_path=path,
                code="invalid_salary_operand",
                message=f"Invalid salary operand structure: {exc}",
                severity="error",
            )
        )
        return None, issues


def validate_criteria_and_preferences(
    policy: SearchPolicy,
) -> list[ValidationIssue]:
    """Validate hard criteria, preferences, exclusions, relevance configuration, and context strategy."""
    issues: list[ValidationIssue] = []
    seen_rule_ids: dict[str, str] = {}  # rule_id -> path

    # 1. Regions
    if not isinstance(policy.regions, list):
        issues.append(
            ValidationIssue(
                field_path="regions",
                code="invalid_type",
                message="regions must be a list of region strings",
                severity="error",
            )
        )
    else:
        for idx, reg in enumerate(policy.regions):
            if not isinstance(reg, str) or not reg.strip():
                issues.append(
                    ValidationIssue(
                        field_path=f"regions[{idx}]",
                        code="empty_region",
                        message="Region item cannot be empty or non-string",
                        severity="error",
                    )
                )

    # 2. Hard criteria
    for idx, crit in enumerate(policy.hard_criteria):
        crit_path = f"hard_criteria[{idx}]"

        # Unique criterion_id
        if not crit.criterion_id or not crit.criterion_id.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.criterion_id",
                    code="empty_criterion_id",
                    message="criterion_id cannot be blank",
                    severity="error",
                )
            )
        elif crit.criterion_id in seen_rule_ids:
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.criterion_id",
                    code="duplicate_criterion_id",
                    message=(
                        f"Criterion ID '{crit.criterion_id}' is already declared at {seen_rule_ids[crit.criterion_id]}"
                    ),
                    severity="error",
                )
            )
        else:
            seen_rule_ids[crit.criterion_id] = crit_path

        # Name
        if not crit.name or not crit.name.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.name",
                    code="empty_criterion_name",
                    message="Criterion name cannot be blank",
                    severity="error",
                )
            )

        # Field validation
        field_name = crit.field.strip() if crit.field else ""
        if is_candidate_field(field_name):
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.field",
                    code="forbidden_candidate_target",
                    message=(
                        f"Field '{crit.field}' refers to candidate facts which belong to C01 ProfileSnapshot, "
                        "not C02 SearchPolicy. Search policy targets only job posting properties."
                    ),
                    severity="error",
                )
            )
            continue
        elif is_skills_target(field_name):
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.field",
                    code="unsupported_target",
                    message=(
                        "Field 'skills' is not a property of C06 NormalizedPosting. "
                        "Target 'description_clean' or 'title' for keyword matching instead, "
                        "or define skill keywords in relevance_configuration."
                    ),
                    severity="error",
                )
            )
            continue
        elif field_name not in TARGET_CATALOG:
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.field",
                    code="unsupported_target",
                    message=(
                        f"Target field '{crit.field}' is not in the supported C06 target catalog. "
                        f"Supported targets: {sorted(TARGET_CATALOG.keys())}"
                    ),
                    severity="error",
                )
            )
            continue

        target_def = TARGET_CATALOG[field_name]

        # Operator validation
        op = crit.operator.strip().lower() if crit.operator else ""
        if op not in target_def.allowed_operators:
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.operator",
                    code="unsupported_operator",
                    message=(
                        f"Operator '{crit.operator}' is not supported for field '{field_name}'. "
                        f"Allowed operators: {sorted(target_def.allowed_operators)}"
                    ),
                    severity="error",
                )
            )
            continue

        # Operand validation
        exp_val = crit.expected_value
        if exp_val is None:
            issues.append(
                ValidationIssue(
                    field_path=f"{crit_path}.expected_value",
                    code="missing_expected_value",
                    message="expected_value cannot be null",
                    severity="error",
                )
            )
            continue

        # Salary operand check
        if target_def.is_compensation:
            _, sal_issues = _validate_salary_operand(exp_val, f"{crit_path}.expected_value")
            issues.extend(sal_issues)
        # Enum target check (workplace_type, employment_type)
        elif target_def.valid_enum_values is not None:
            if op in {"equals", "not_equals"}:
                if not isinstance(exp_val, str) or exp_val not in target_def.valid_enum_values:
                    issues.append(
                        ValidationIssue(
                            field_path=f"{crit_path}.expected_value",
                            code="invalid_enum_value",
                            message=(
                                f"Value '{exp_val}' is invalid for enum field '{field_name}'. "
                                f"Allowed values: {sorted(target_def.valid_enum_values)}"
                            ),
                            severity="error",
                        )
                    )
            elif op in {"in", "not_in"}:
                if not isinstance(exp_val, list) or len(exp_val) == 0:
                    issues.append(
                        ValidationIssue(
                            field_path=f"{crit_path}.expected_value",
                            code="empty_operand_set",
                            message=f"Operator '{op}' requires a non-empty list of values",
                            severity="error",
                        )
                    )
                else:
                    for v_idx, v in enumerate(exp_val):
                        if not isinstance(v, str) or v not in target_def.valid_enum_values:
                            issues.append(
                                ValidationIssue(
                                    field_path=f"{crit_path}.expected_value[{v_idx}]",
                                    code="invalid_enum_value",
                                    message=(
                                        f"Value '{v}' is invalid for enum field '{field_name}'. "
                                        f"Allowed values: {sorted(target_def.valid_enum_values)}"
                                    ),
                                    severity="error",
                                )
                            )
        # String list / set operators
        elif op in {"in", "not_in"}:
            if not isinstance(exp_val, list) or len(exp_val) == 0:
                issues.append(
                    ValidationIssue(
                        field_path=f"{crit_path}.expected_value",
                        code="empty_operand_set",
                        message=f"Operator '{op}' requires a non-empty list of string values",
                        severity="error",
                    )
                )
            else:
                for v_idx, v in enumerate(exp_val):
                    if not isinstance(v, str) or not v.strip():
                        issues.append(
                            ValidationIssue(
                                field_path=f"{crit_path}.expected_value[{v_idx}]",
                                code="empty_operand_value",
                                message="Operand string cannot be empty or whitespace only",
                                severity="error",
                            )
                        )
        # String scalar operators
        elif op in {"equals", "not_equals", "contains", "not_contains"}:
            if isinstance(exp_val, bool):
                issues.append(
                    ValidationIssue(
                        field_path=f"{crit_path}.expected_value",
                        code="boolean_as_operand",
                        message=f"Boolean operand is invalid for string operator '{op}'",
                        severity="error",
                    )
                )
            elif not isinstance(exp_val, str) or not exp_val.strip():
                issues.append(
                    ValidationIssue(
                        field_path=f"{crit_path}.expected_value",
                        code="empty_operand_value",
                        message="Operand string cannot be empty or whitespace only",
                        severity="error",
                    )
                )

    # 3. Preferences
    for idx, pref in enumerate(policy.preferences):
        pref_path = f"preferences[{idx}]"

        # Rule ID uniqueness
        if not pref.rule_id or not pref.rule_id.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.rule_id",
                    code="empty_rule_id",
                    message="Preference rule_id cannot be blank",
                    severity="error",
                )
            )
        elif pref.rule_id in seen_rule_ids:
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.rule_id",
                    code="duplicate_rule_id",
                    message=(
                        f"Rule ID '{pref.rule_id}' collides with existing rule ID at {seen_rule_ids[pref.rule_id]}"
                    ),
                    severity="error",
                )
            )
        else:
            seen_rule_ids[pref.rule_id] = pref_path

        # Name
        if not pref.name or not pref.name.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.name",
                    code="empty_rule_name",
                    message="Preference rule name cannot be blank",
                    severity="error",
                )
            )

        # Target field
        field_name = pref.field.strip() if pref.field else ""
        if is_candidate_field(field_name):
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.field",
                    code="forbidden_candidate_target",
                    message=(
                        f"Field '{pref.field}' refers to candidate facts which belong to C01 ProfileSnapshot, "
                        "not C02 SearchPolicy. Search policy targets only job posting properties."
                    ),
                    severity="error",
                )
            )
            continue
        elif is_skills_target(field_name):
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.field",
                    code="unsupported_target",
                    message=(
                        "Field 'skills' is not a property of C06 NormalizedPosting. "
                        "Target 'description_clean' or 'title' for keyword preferences, "
                        "or define skill keywords in relevance_configuration."
                    ),
                    severity="error",
                )
            )
            continue
        elif field_name not in TARGET_CATALOG:
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.field",
                    code="unsupported_target",
                    message=f"Target field '{pref.field}' is not in the supported target catalog",
                    severity="error",
                )
            )
            continue
        elif not TARGET_CATALOG[field_name].allowed_for_preferences:
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.field",
                    code="target_not_allowed_for_preferences",
                    message=f"Field '{field_name}' cannot be used as a soft preference",
                    severity="error",
                )
            )
            continue

        # Weight validation
        if not math.isfinite(pref.weight) or pref.weight < 0.0 or pref.weight > 1.0:
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.weight",
                    code="invalid_preference_weight",
                    message=f"Preference weight must be a finite float in [0.0, 1.0], got {pref.weight}",
                    severity="error",
                )
            )

        # Preferred values
        if not pref.preferred_values:
            issues.append(
                ValidationIssue(
                    field_path=f"{pref_path}.preferred_values",
                    code="empty_preferred_values",
                    message="preferred_values must contain at least one preferred value",
                    severity="warning",
                )
            )
        else:
            for p_idx, pv in enumerate(pref.preferred_values):
                if not isinstance(pv, str) or not pv.strip():
                    issues.append(
                        ValidationIssue(
                            field_path=f"{pref_path}.preferred_values[{p_idx}]",
                            code="empty_preferred_value",
                            message="Preferred value string cannot be empty or whitespace only",
                            severity="error",
                        )
                    )

    # 4. Exclusions
    for idx, exc in enumerate(policy.exclusions):
        exc_path = f"exclusions[{idx}]"
        if not isinstance(exc, str) or not exc.strip():
            issues.append(
                ValidationIssue(
                    field_path=exc_path,
                    code="empty_exclusion",
                    message="Exclusion item cannot be empty or whitespace only",
                    severity="error",
                )
            )
        elif REGEX_CHARACTERS.search(exc):
            issues.append(
                ValidationIssue(
                    field_path=exc_path,
                    code="regex_exclusion_forbidden",
                    message=(
                        f"Exclusion '{exc}' contains regular expression meta-characters. "
                        "Exclusions must be literal strings; regex patterns are forbidden."
                    ),
                    severity="error",
                )
            )

    # 5. Relevance Configuration
    rel = policy.relevance_configuration
    if rel.score_scale != "0-100":
        issues.append(
            ValidationIssue(
                field_path="relevance_configuration.score_scale",
                code="unsupported_score_scale",
                message=f"Only score_scale '0-100' is supported, got '{rel.score_scale}'",
                severity="error",
            )
        )

    if rel.min_score_threshold is not None:
        if not math.isfinite(rel.min_score_threshold) or rel.min_score_threshold < 0.0 or rel.min_score_threshold > 100.0:
            issues.append(
                ValidationIssue(
                    field_path="relevance_configuration.min_score_threshold",
                    code="invalid_score_threshold",
                    message=(
                        f"min_score_threshold must be a finite float in [0.0, 100.0] or null, "
                        f"got {rel.min_score_threshold}"
                    ),
                    severity="error",
                )
            )

    for idx, kw in enumerate(rel.broad_keywords):
        if not isinstance(kw, str) or not kw.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"relevance_configuration.broad_keywords[{idx}]",
                    code="empty_broad_keyword",
                    message="Broad keyword cannot be empty or whitespace only",
                    severity="error",
                )
            )

    for idx, kw in enumerate(rel.negative_keywords):
        if not isinstance(kw, str) or not kw.strip():
            issues.append(
                ValidationIssue(
                    field_path=f"relevance_configuration.negative_keywords[{idx}]",
                    code="empty_negative_keyword",
                    message="Negative keyword cannot be empty or whitespace only",
                    severity="error",
                )
            )

    # 6. Primary context strategy
    if policy.primary_context_strategy not in {ContextStrategy.JSON, ContextStrategy.RAG}:
        issues.append(
            ValidationIssue(
                field_path="primary_context_strategy",
                code="unsupported_context_strategy",
                message=(
                    f"primary_context_strategy must be 'json' or 'rag', got '{policy.primary_context_strategy}'"
                ),
                severity="error",
            )
        )

    return issues

