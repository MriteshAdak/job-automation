"""Bounded cross-policy conflict detection for C02 SearchPolicy."""

from __future__ import annotations

from typing import Any

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    SearchPolicy,
)
from job_automation.policy.models import SalaryOperand
from job_automation.policy.vocabulary import NormalizedVocabulary, normalize_lookup


def _extract_allowed_set(crit: HardCriterion) -> set[str] | None:
    """Extract set of allowed values for scalar fields with equals/in operators."""
    op = crit.operator.strip().lower()
    if op == "equals" and isinstance(crit.expected_value, str):
        return {crit.expected_value.strip().lower()}
    if op == "in" and isinstance(crit.expected_value, list):
        return {str(x).strip().lower() for x in crit.expected_value if str(x).strip()}
    return None


def detect_policy_conflicts(
    policy: SearchPolicy,
    vocabulary: NormalizedVocabulary,
) -> list[ValidationIssue]:
    """Inspect criteria, preferences, exclusions, and relevance config for provable contradictions."""
    issues: list[ValidationIssue] = []

    # 1. Scalar domain contradictions in hard criteria (e.g. workplace_type)
    scalar_fields = {"workplace_type", "employment_type", "advert_language"}
    crit_by_scalar: dict[str, list[HardCriterion]] = {}
    for crit in policy.hard_criteria:
        f = crit.field.strip()
        if f in scalar_fields:
            crit_by_scalar.setdefault(f, []).append(crit)

    for f, crits in crit_by_scalar.items():
        if len(crits) < 2:
            continue
        # Compare pairs of criteria on the same scalar field
        for i in range(len(crits)):
            for j in range(i + 1, len(crits)):
                c1 = crits[i]
                c2 = crits[j]
                s1 = _extract_allowed_set(c1)
                s2 = _extract_allowed_set(c2)
                if s1 is not None and s2 is not None:
                    # If intersection is empty, the criteria are mutually exclusive
                    if not (s1 & s2):
                        issues.append(
                            ValidationIssue(
                                field_path=f"hard_criteria['{c2.criterion_id}']",
                                code="contradictory_hard_criteria",
                                message=(
                                    f"Hard criterion '{c2.criterion_id}' ({c2.name}) contradicts "
                                    f"criterion '{c1.criterion_id}' ({c1.name}) on scalar field '{f}'. "
                                    f"Allowed sets {sorted(s2)} and {sorted(s1)} are disjoint."
                                ),
                                severity="error",
                            )
                        )

                # Check equals vs not_equals
                op1 = c1.operator.strip().lower()
                op2 = c2.operator.strip().lower()
                v1 = str(c1.expected_value).strip().lower() if isinstance(c1.expected_value, str) else None
                v2 = str(c2.expected_value).strip().lower() if isinstance(c2.expected_value, str) else None
                if v1 and v2 and v1 == v2:
                    if (op1 == "equals" and op2 == "not_equals") or (op1 == "not_equals" and op2 == "equals"):
                        issues.append(
                            ValidationIssue(
                                field_path=f"hard_criteria['{c2.criterion_id}']",
                                code="contradictory_hard_criteria",
                                message=(
                                    f"Hard criterion '{c2.criterion_id}' ({op2} '{v2}') directly contradicts "
                                    f"criterion '{c1.criterion_id}' ({op1} '{v1}') on field '{f}'."
                                ),
                                severity="error",
                            )
                        )

    # 2. Inverted salary bounds
    min_sal_crits: list[tuple[HardCriterion, SalaryOperand]] = []
    max_sal_crits: list[tuple[HardCriterion, SalaryOperand]] = []
    for crit in policy.hard_criteria:
        f = crit.field.strip()
        op = crit.operator.strip().lower()
        if (f == "compensation.min_amount" or f == "compensation") and op in {"gte", "gt"}:
            if isinstance(crit.expected_value, dict):
                try:
                    operand = SalaryOperand.model_validate(crit.expected_value)
                    min_sal_crits.append((crit, operand))
                except Exception:
                    pass
        elif (f == "compensation.max_amount" or f == "compensation") and op in {"lte", "lt"}:
            if isinstance(crit.expected_value, dict):
                try:
                    operand = SalaryOperand.model_validate(crit.expected_value)
                    max_sal_crits.append((crit, operand))
                except Exception:
                    pass

    for min_crit, min_op in min_sal_crits:
        for max_crit, max_op in max_sal_crits:
            # Check unit comparability: currency and period must match
            if min_op.currency == max_op.currency and min_op.period == max_op.period:
                if min_op.amount > max_op.amount:
                    issues.append(
                        ValidationIssue(
                            field_path=f"hard_criteria['{max_crit.criterion_id}']",
                            code="inverted_numeric_bounds",
                            message=(
                                f"Inverted salary bounds: minimum threshold ({min_op.amount} {min_op.currency}/{min_op.period}) "
                                f"in criterion '{min_crit.criterion_id}' exceeds maximum ceiling "
                                f"({max_op.amount} {max_op.currency}/{max_op.period}) in criterion '{max_crit.criterion_id}'."
                            ),
                            severity="error",
                        )
                    )

    # 3. Required term vs Exclusions conflict
    # Build normalized lookup for exclusions
    normalized_exclusions: dict[str, str] = {}
    for exc in policy.exclusions:
        if isinstance(exc, str) and exc.strip():
            k = normalize_lookup(exc)
            normalized_exclusions[k] = exc.strip()

    for crit in policy.hard_criteria:
        f = crit.field.strip()
        op = crit.operator.strip().lower()
        if f in {"title", "company_name_hint"}:
            terms_to_check: list[str] = []
            if op in {"equals", "contains"} and isinstance(crit.expected_value, str):
                terms_to_check.append(crit.expected_value)
            elif op == "in" and isinstance(crit.expected_value, list):
                terms_to_check.extend([str(x) for x in crit.expected_value if isinstance(x, str)])

            for term in terms_to_check:
                lk = normalize_lookup(term)
                # Check direct match
                if lk in normalized_exclusions:
                    exc_orig = normalized_exclusions[lk]
                    issues.append(
                        ValidationIssue(
                            field_path=f"hard_criteria['{crit.criterion_id}']",
                            code="exclusion_conflict",
                            message=(
                                f"Hard criterion '{crit.criterion_id}' requires '{term}' on field '{f}', "
                                f"which is explicitly listed in exclusions as '{exc_orig}'."
                            ),
                            severity="error",
                        )
                    )
                # Check via role vocabulary alias resolution
                if f == "title":
                    canonical = vocabulary.resolve_role(term)
                    if canonical:
                        can_lk = normalize_lookup(canonical)
                        if can_lk in normalized_exclusions and can_lk != lk:
                            exc_orig = normalized_exclusions[can_lk]
                            issues.append(
                                ValidationIssue(
                                    field_path=f"hard_criteria['{crit.criterion_id}']",
                                    code="exclusion_conflict",
                                    message=(
                                        f"Hard criterion '{crit.criterion_id}' requires '{term}' (resolves to role '{canonical}'), "
                                        f"whose canonical name is excluded as '{exc_orig}'."
                                    ),
                                    severity="error",
                                )
                            )

    # 4. Soft preference vs Hard criterion disagreement (Warning)
    for pref in policy.preferences:
        pref_f = pref.field.strip()
        if pref_f in scalar_fields:
            # Find hard criteria on the same scalar field
            matching_hard = [c for c in policy.hard_criteria if c.field.strip() == pref_f]
            for h in matching_hard:
                hard_allowed = _extract_allowed_set(h)
                if hard_allowed is not None:
                    pref_values = {v.strip().lower() for v in pref.preferred_values if isinstance(v, str)}
                    # If all preferred values fall outside hard allowed set, preference is unreachable
                    if pref_values and not (pref_values & hard_allowed):
                        issues.append(
                            ValidationIssue(
                                field_path=f"preferences['{pref.rule_id}']",
                                code="unreachable_preference",
                                message=(
                                    f"Soft preference '{pref.rule_id}' for {sorted(pref_values)} on '{pref_f}' "
                                    f"is unreachable because hard criterion '{h.criterion_id}' limits allowed values to "
                                    f"{sorted(hard_allowed)}."
                                ),
                                severity="warning",
                            )
                        )

    # 5. Relevance keyword conflicts
    broad_kws = {normalize_lookup(k): k for k in policy.relevance_configuration.broad_keywords if isinstance(k, str) and k.strip()}
    neg_kws = {normalize_lookup(k): k for k in policy.relevance_configuration.negative_keywords if isinstance(k, str) and k.strip()}

    # Check broad vs negative keywords overlap (Error)
    for lk, orig_broad in broad_kws.items():
        if lk in neg_kws:
            orig_neg = neg_kws[lk]
            issues.append(
                ValidationIssue(
                    field_path="relevance_configuration.broad_keywords",
                    code="contradictory_relevance_keywords",
                    message=(
                        f"Keyword '{orig_broad}' appears in both broad_keywords and "
                        f"negative_keywords ('{orig_neg}')."
                    ),
                    severity="error",
                )
            )

    # Check broad keywords vs exclusions overlap (Warning)
    for lk, orig_broad in broad_kws.items():
        if lk in normalized_exclusions:
            orig_exc = normalized_exclusions[lk]
            issues.append(
                ValidationIssue(
                    field_path="relevance_configuration.broad_keywords",
                    code="exclusion_keyword_overlap",
                    message=(
                        f"Broad recall keyword '{orig_broad}' overlaps with exclusion '{orig_exc}'."
                    ),
                    severity="warning",
                )
            )

    # Sort issues stably by field_path, code, severity
    issues.sort(key=lambda i: (i.field_path, i.code, i.severity))
    return issues

