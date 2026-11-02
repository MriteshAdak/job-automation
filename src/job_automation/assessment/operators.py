"""Allowlisted evaluation operators for C06 NormalizedPosting fields."""

from __future__ import annotations

from typing import Any

from job_automation.assessment.errors import AssessmentConfigurationError
from job_automation.assessment.literal_matching import contains_literal_phrase, find_literal_matches
from job_automation.assessment.models import FactualOutcome
from job_automation.contracts.postings import NormalizedPosting
from job_automation.policy.vocabulary import normalize_lookup


def evaluate_field_operator(
    field_path: str,
    operator: str,
    expected_value: Any,
    posting: NormalizedPosting,
) -> tuple[FactualOutcome, str, str | None, tuple[int, int] | None]:
    """Evaluate an allowlisted operator on a posting field.

    Returns:
        tuple[FactualOutcome, reason, quotation_snippet, span]
    """
    op = operator.lower().strip()

    # Special handling for multi-location targets
    if field_path.startswith("locations."):
        return _evaluate_locations(field_path, op, expected_value, posting)

    # Workplace type and Employment type
    if field_path in {"workplace_type", "employment_type"}:
        return _evaluate_enum_field(field_path, op, expected_value, posting)

    # Remote eligibility restrictions
    if field_path == "remote_eligibility_restrictions":
        return _evaluate_remote_restrictions(op, expected_value, posting)

    # General text/scalar fields (title, company_name_hint, description_clean, advert_language)
    return _evaluate_text_field(field_path, op, expected_value, posting)


def _evaluate_locations(
    field_path: str,
    op: str,
    expected_value: Any,
    posting: NormalizedPosting,
) -> tuple[FactualOutcome, str, str | None, tuple[int, int] | None]:
    if not posting.locations:
        return FactualOutcome.UNKNOWN, "Posting has no stated locations", None, None

    attr = field_path.split(".", 1)[1]  # country, city, or region

    loc_values: list[str | None] = []
    for loc in posting.locations:
        v = getattr(loc, attr, None)
        loc_values.append(v)

    known_values = [v for v in loc_values if v is not None]
    has_unknown_alternatives = len(known_values) < len(loc_values)

    all_snippets = ", ".join(loc.raw_text for loc in posting.locations)

    # Normalize expected values for casefold matching
    if isinstance(expected_value, list):
        expected_set = {normalize_lookup(str(x)) for x in expected_value}
    else:
        expected_set = {normalize_lookup(str(expected_value))}

    if op in {"equals", "in"}:
        # Positive existential check: pass if any known alternative matches
        for v in known_values:
            if normalize_lookup(v) in expected_set:
                return (
                    FactualOutcome.PASS,
                    f"Location alternative '{v}' satisfies required location criteria",
                    all_snippets,
                    None,
                )
        # If no alternative matched, but some alternatives had unknown attributes
        if has_unknown_alternatives:
            return (
                FactualOutcome.UNKNOWN,
                f"No known location matched, but posting contains incomplete location alternatives: {all_snippets}",
                all_snippets,
                None,
            )
        # All alternatives known and none matched
        return (
            FactualOutcome.FAIL,
            f"None of the stated locations [{', '.join(known_values)}] matched required {expected_value}",
            all_snippets,
            None,
        )

    if op in {"not_equals", "not_in"}:
        # Negative universal check: fail if ANY alternative matches the forbidden value
        for v in known_values:
            if normalize_lookup(v) in expected_set:
                return (
                    FactualOutcome.FAIL,
                    f"Location alternative '{v}' matches excluded location {expected_value}",
                    all_snippets,
                    None,
                )
        if has_unknown_alternatives:
            return (
                FactualOutcome.UNKNOWN,
                f"No stated location matched excluded set, but incomplete location alternatives exist: {all_snippets}",
                all_snippets,
                None,
            )
        return (
            FactualOutcome.PASS,
            f"None of the stated locations [{', '.join(known_values)}] match excluded {expected_value}",
            all_snippets,
            None,
        )

    raise AssessmentConfigurationError(f"Unsupported operator '{op}' for '{field_path}'")


def _evaluate_enum_field(
    field_path: str,
    op: str,
    expected_value: Any,
    posting: NormalizedPosting,
) -> tuple[FactualOutcome, str, str | None, tuple[int, int] | None]:
    if field_path == "workplace_type":
        actual = posting.workplace_type.value if posting.workplace_type else "unknown"
    else:
        actual = posting.employment_type.value if posting.employment_type else "unknown"

    if actual == "unknown":
        return (
            FactualOutcome.UNKNOWN,
            f"Posting has unspecified/unknown '{field_path}'",
            f"{field_path}: unknown",
            None,
        )

    norm_actual = normalize_lookup(actual)

    if isinstance(expected_value, list):
        expected_set = {normalize_lookup(str(x)) for x in expected_value}
    else:
        expected_set = {normalize_lookup(str(expected_value))}

    if op == "equals":
        if norm_actual in expected_set:
            return FactualOutcome.PASS, f"{field_path} '{actual}' equals expected '{expected_value}'", actual, None
        return FactualOutcome.FAIL, f"{field_path} '{actual}' does not equal expected '{expected_value}'", actual, None

    if op == "not_equals":
        if norm_actual not in expected_set:
            return FactualOutcome.PASS, f"{field_path} '{actual}' does not equal '{expected_value}'", actual, None
        return FactualOutcome.FAIL, f"{field_path} '{actual}' equals excluded '{expected_value}'", actual, None

    if op == "in":
        if norm_actual in expected_set:
            return FactualOutcome.PASS, f"{field_path} '{actual}' is in {expected_value}", actual, None
        return FactualOutcome.FAIL, f"{field_path} '{actual}' is not in {expected_value}", actual, None

    if op == "not_in":
        if norm_actual not in expected_set:
            return FactualOutcome.PASS, f"{field_path} '{actual}' is not in {expected_value}", actual, None
        return FactualOutcome.FAIL, f"{field_path} '{actual}' is in excluded set {expected_value}", actual, None

    raise AssessmentConfigurationError(f"Unsupported operator '{op}' for enum field '{field_path}'")


def _evaluate_remote_restrictions(
    op: str,
    expected_value: Any,
    posting: NormalizedPosting,
) -> tuple[FactualOutcome, str, str | None, tuple[int, int] | None]:
    restrictions = posting.remote_eligibility_restrictions
    if not restrictions:
        return (
            FactualOutcome.UNKNOWN,
            "Posting has unstated remote eligibility restrictions (remote does not imply worldwide)",
            None,
            None,
        )

    norm_restrictions = {normalize_lookup(r) for r in restrictions}
    all_restr_str = f"[{', '.join(restrictions)}]"

    if isinstance(expected_value, list):
        target_set = {normalize_lookup(str(x)) for x in expected_value}
    else:
        target_set = {normalize_lookup(str(expected_value))}

    if op in {"contains", "in"}:
        if any(t in norm_restrictions for t in target_set):
            return FactualOutcome.PASS, f"Remote restrictions {all_restr_str} include expected {expected_value}", all_restr_str, None
        return FactualOutcome.FAIL, f"Remote restrictions {all_restr_str} do not include {expected_value}", all_restr_str, None

    if op in {"not_contains", "not_in"}:
        if not any(t in norm_restrictions for t in target_set):
            return FactualOutcome.PASS, f"Remote restrictions {all_restr_str} do not include {expected_value}", all_restr_str, None
        return FactualOutcome.FAIL, f"Remote restrictions {all_restr_str} contain excluded {expected_value}", all_restr_str, None

    if op == "equals":
        if norm_restrictions == target_set:
            return FactualOutcome.PASS, f"Remote restrictions {all_restr_str} equal {expected_value}", all_restr_str, None
        return FactualOutcome.FAIL, f"Remote restrictions {all_restr_str} do not equal {expected_value}", all_restr_str, None

    raise AssessmentConfigurationError(f"Unsupported operator '{op}' for remote_eligibility_restrictions")


def _evaluate_text_field(
    field_path: str,
    op: str,
    expected_value: Any,
    posting: NormalizedPosting,
) -> tuple[FactualOutcome, str, str | None, tuple[int, int] | None]:
    if field_path == "title":
        raw_text = posting.title
    elif field_path == "description_clean":
        raw_text = posting.description_clean
    elif field_path == "company_name_hint":
        raw_text = posting.company_name_hint
    elif field_path == "advert_language":
        raw_text = posting.advert_language or ""
    else:
        raise AssessmentConfigurationError(f"Unsupported text target '{field_path}'")

    if not raw_text or not raw_text.strip():
        return FactualOutcome.UNKNOWN, f"Field '{field_path}' is absent or empty in posting", None, None

    norm_text = normalize_lookup(raw_text)

    if op == "equals":
        expected_str = normalize_lookup(str(expected_value))
        if norm_text == expected_str:
            return FactualOutcome.PASS, f"{field_path} equals '{expected_value}'", raw_text, None
        return FactualOutcome.FAIL, f"{field_path} does not equal '{expected_value}'", raw_text, None

    if op == "not_equals":
        expected_str = normalize_lookup(str(expected_value))
        if norm_text != expected_str:
            return FactualOutcome.PASS, f"{field_path} does not equal '{expected_value}'", raw_text, None
        return FactualOutcome.FAIL, f"{field_path} equals excluded '{expected_value}'", raw_text, None

    if op == "contains":
        target = str(expected_value)
        matches = find_literal_matches(raw_text, target)
        if matches:
            start, end, snippet = matches[0]
            return FactualOutcome.PASS, f"{field_path} contains '{target}'", snippet, (start, end)
        return FactualOutcome.FAIL, f"{field_path} does not contain '{target}'", raw_text[:200], None

    if op == "not_contains":
        target = str(expected_value)
        matches = find_literal_matches(raw_text, target)
        if not matches:
            return FactualOutcome.PASS, f"{field_path} does not contain excluded '{target}'", raw_text[:200], None
        start, end, snippet = matches[0]
        return FactualOutcome.FAIL, f"{field_path} contains excluded '{target}'", snippet, (start, end)

    if op == "in":
        if not isinstance(expected_value, list):
            raise AssessmentConfigurationError(f"Operator 'in' requires a list operand")
        for exp in expected_value:
            if norm_text == normalize_lookup(str(exp)):
                return FactualOutcome.PASS, f"{field_path} is in {expected_value}", raw_text, None
        return FactualOutcome.FAIL, f"{field_path} is not in {expected_value}", raw_text, None

    if op == "not_in":
        if not isinstance(expected_value, list):
            raise AssessmentConfigurationError(f"Operator 'not_in' requires a list operand")
        for exp in expected_value:
            if norm_text == normalize_lookup(str(exp)):
                return FactualOutcome.FAIL, f"{field_path} matches excluded '{exp}' in {expected_value}", raw_text, None
        return FactualOutcome.PASS, f"{field_path} is not in {expected_value}", raw_text, None

    raise AssessmentConfigurationError(f"Unsupported operator '{op}' for text field '{field_path}'")

