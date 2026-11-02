"""Shared inclusion rules for JSON and RAG context consumers.

Guarantees:
- Both JSON and RAG strategies receive identical eligible evidence for the same snapshot and purpose.
- Enforces strict purpose-based permission checks (assessment, cv, cover_letter).
- Restricted parent context cannot leak through children; mandatory context conflicts fail fast.
- Deterministic fact ordering.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.contracts.profile import CandidateFact, ProfileSnapshot
from job_automation.profile.errors import (
    InclusionConflictError,
    ProfileValidationError,
)
from job_automation.profile.models import (
    DEFAULT_RULE_VERSION,
    SUPPORTED_PURPOSES,
    ProfileInclusionView,
)
from job_automation.profile.validation import compare_precision_dates


def _fact_sort_key(fact: CandidateFact) -> tuple[int, str, str]:
    """Deterministic sort key for facts: start_date descending (nulls last), then fact_id."""
    if fact.start_date is not None:
        # We invert lexical value or put non-nulls first (0)
        return (0, fact.start_date.value, str(fact.fact_id))
    return (1, "", str(fact.fact_id))


class InclusionRules:
    """Evaluates fact permissions and builds deterministic ProfileInclusionView."""

    def __init__(self, rule_version: str = DEFAULT_RULE_VERSION) -> None:
        self.rule_version = rule_version

    def evaluate_inclusion(
        self,
        snapshot: ProfileSnapshot,
        purpose: str,
        mandatory_fact_ids: Sequence[uuid.UUID] | None = None,
    ) -> ProfileInclusionView:
        """Filter snapshot facts by purpose, verifying parent privacy and mandatory requirements."""
        if purpose not in SUPPORTED_PURPOSES:
            raise ProfileValidationError(
                f"Unsupported inclusion purpose '{purpose}'. Must be one of {sorted(SUPPORTED_PURPOSES)}",
                field_path="purpose",
                code="UNSUPPORTED_PURPOSE",
            )

        mandatory_set = set(mandatory_fact_ids or [])
        fact_by_id = {f.fact_id: f for f in snapshot.evidence_records}

        # Check for mandatory IDs that do not exist in the snapshot
        missing_mandatory = mandatory_set - set(fact_by_id.keys())
        if missing_mandatory:
            sorted_missing = sorted(missing_mandatory, key=str)
            raise ProfileValidationError(
                f"Mandatory fact '{sorted_missing[0]}' not found in profile snapshot",
                field_path="mandatory_fact_ids",
                code="MANDATORY_FACT_NOT_FOUND",
            )

        # Check permission for each fact
        permitted_ids: set[uuid.UUID] = set()
        excluded_count = 0
        warnings: list[str] = []

        for fact in snapshot.evidence_records:
            if not fact.allowed_uses or purpose not in fact.allowed_uses:
                excluded_count += 1
                if fact.fact_id in mandatory_set:
                    raise InclusionConflictError(
                        f"Mandatory fact '{fact.fact_id}' is restricted from purpose '{purpose}'"
                    )
            else:
                permitted_ids.add(fact.fact_id)

        # Validate parent relationships for permitted facts in stable order
        eligible_facts: list[CandidateFact] = []
        mandatory_facts: list[CandidateFact] = []

        for fact in snapshot.evidence_records:
            fid = fact.fact_id
            if fid not in permitted_ids:
                continue

            parent_id = fact.parent_id
            if parent_id is not None and parent_id not in permitted_ids:
                # Parent is restricted
                if parent_id in mandatory_set:
                    raise InclusionConflictError(
                        f"Mandatory parent '{parent_id}' of fact '{fid}' is restricted from purpose '{purpose}'"
                    )
                warnings.append(
                    f"Parent fact '{parent_id}' of fact '{fid}' is restricted and omitted from '{purpose}' view"
                )

            eligible_facts.append(fact)
            if fid in mandatory_set:
                mandatory_facts.append(fact)

        warnings.sort()

        # Deterministic sorting (descending start_date, then fact_id)
        eligible_facts.sort(key=lambda f: (0 if f.start_date else 1, -(int(f.start_date.value.split('-')[0])) if f.start_date else 0, str(f.fact_id)))
        mandatory_facts.sort(key=lambda f: (0 if f.start_date else 1, -(int(f.start_date.value.split('-')[0])) if f.start_date else 0, str(f.fact_id)))

        return ProfileInclusionView(
            profile_version=snapshot.profile_version,
            candidate_id=snapshot.candidate_id,
            purpose=purpose,
            rule_version=self.rule_version,
            eligible_facts=eligible_facts,
            eligible_fact_ids=[f.fact_id for f in eligible_facts],
            mandatory_facts=mandatory_facts,
            explicit_eligibility=snapshot.explicit_eligibility,
            excluded_fact_count=excluded_count,
            warnings=warnings,
        )

