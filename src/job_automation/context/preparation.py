"""Shared profile context preparation for CONTEXT-01 JSON and future RAG consumers.

Implements Mandatory Context Policy v1:
- Applies permission filtering before deriving chronology anchors (private facts are never mandatory).
- Derived chronology anchors: all permitted employment and education facts.
- Derived ancestor chains: all permitted parent facts needed to interpret permitted child evidence.
- Explicit caller mandatory IDs: validated against snapshot and permissions.
- Derives structured chronology references preserving exact dates, precision, and version citations.
- Shares exact evidence universe and mandatory set with future RAG.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.errors import (
    ContextPermissionError,
    ContextValidationError,
)
from job_automation.context.records import PreparedProfileContext
from job_automation.contracts.context import ChronologyReference
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileSnapshot,
)
from job_automation.profile.errors import (
    InclusionConflictError,
    ProfileValidationError,
)
from job_automation.profile.inclusion import InclusionRules
from job_automation.profile.models import (
    DEFAULT_RULE_VERSION,
    SUPPORTED_PURPOSES,
    ProfileInclusionView,
)
from job_automation.profile.validation import validate_snapshot

DEFAULT_MANDATORY_POLICY_VERSION = "v1"


class ProfileContextPreparer:
    """Prepares permitted evidence universe, chronology anchors, and mandatory context.

    Reusable across full-profile JSON context and future RAG retrieval.
    """

    def __init__(
        self,
        inclusion_rule_version: str = DEFAULT_RULE_VERSION,
        mandatory_policy_version: str = DEFAULT_MANDATORY_POLICY_VERSION,
    ) -> None:
        self.inclusion_rule_version = inclusion_rule_version
        self.mandatory_policy_version = mandatory_policy_version
        self._inclusion_rules = InclusionRules(rule_version=inclusion_rule_version)

    def prepare_context(
        self,
        snapshot: ProfileSnapshot,
        purpose: str,
        explicit_mandatory_ids: Sequence[uuid.UUID] | None = None,
    ) -> PreparedProfileContext:
        """Validate snapshot and construct the shared PreparedProfileContext."""
        # 1. Validate snapshot invariants (approval, graph, schema version, date ranges)
        try:
            validate_snapshot(snapshot)
        except ProfileValidationError as exc:
            raise ContextValidationError(
                f"Invalid profile snapshot: {str(exc)}",
                field_path=exc.field_path,
                code=exc.code,
            ) from exc

        # 2. Validate purpose
        if purpose not in SUPPORTED_PURPOSES:
            raise ContextValidationError(
                f"Unsupported inclusion purpose '{purpose}'. Must be one of {sorted(SUPPORTED_PURPOSES)}",
                field_path="purpose",
                code="UNSUPPORTED_PURPOSE",
            )

        fact_map = {f.fact_id: f for f in snapshot.evidence_records}

        # 3. Validate caller-specified mandatory IDs
        caller_mandatory = list(explicit_mandatory_ids or [])
        for fid in caller_mandatory:
            if fid not in fact_map:
                raise ContextValidationError(
                    f"Explicit mandatory fact '{fid}' not found in profile snapshot",
                    field_path="explicit_mandatory_fact_ids",
                    code="MANDATORY_FACT_NOT_FOUND",
                )

        # 4. Check permitted facts for this purpose
        permitted_ids: set[uuid.UUID] = set()
        for fact in snapshot.evidence_records:
            if fact.allowed_uses and purpose in fact.allowed_uses:
                permitted_ids.add(fact.fact_id)

        # Verify caller-specified mandatory facts are permitted
        for fid in caller_mandatory:
            if fid not in permitted_ids:
                raise ContextPermissionError(
                    f"Explicit mandatory fact '{fid}' is restricted from purpose '{purpose}'",
                    field_path=f"facts[{fid}].allowed_uses",
                    details={"fact_id": str(fid), "purpose": purpose},
                )

        # 5. Mandatory Context Policy v1: derive mandatory facts and reasons
        mandatory_reasons: dict[str, list[str]] = {}

        def add_reason(fid: uuid.UUID, reason: str) -> None:
            fid_str = str(fid)
            if fid_str not in mandatory_reasons:
                mandatory_reasons[fid_str] = []
            if reason not in mandatory_reasons[fid_str]:
                mandatory_reasons[fid_str].append(reason)

        # A. Chronology anchors: all permitted employment and education facts
        for fid in permitted_ids:
            fact = fact_map[fid]
            if fact.kind == EvidenceFactKind.EMPLOYMENT:
                add_reason(fid, "chronology_employment")
            elif fact.kind == EvidenceFactKind.EDUCATION:
                add_reason(fid, "chronology_education")

        # B. Ancestor chains: permitted ancestors of permitted facts
        for fid in permitted_ids:
            curr = fact_map[fid]
            parent_id = curr.parent_id
            while parent_id is not None:
                if parent_id in fact_map and parent_id in permitted_ids:
                    add_reason(parent_id, "ancestor_chain")
                    parent_id = fact_map[parent_id].parent_id
                else:
                    # Parent is restricted or absent; stop following chain
                    break

        # C. Explicit caller-required facts
        for fid in caller_mandatory:
            add_reason(fid, "caller_required")

        all_mandatory_uuids = [uuid.UUID(fid_str) for fid_str in mandatory_reasons.keys()]

        # 6. Evaluate inclusion using shared InclusionRules
        try:
            view: ProfileInclusionView = self._inclusion_rules.evaluate_inclusion(
                snapshot=snapshot,
                purpose=purpose,
                mandatory_fact_ids=all_mandatory_uuids,
            )
        except InclusionConflictError as exc:
            raise ContextPermissionError(
                str(exc),
                field_path="mandatory_fact_ids",
            ) from exc
        except ProfileValidationError as exc:
            raise ContextValidationError(
                str(exc),
                field_path=exc.field_path,
                code=exc.code,
            ) from exc

        # 7. Construct structured chronology references
        chronology_refs: list[ChronologyReference] = []
        for fact in view.eligible_facts:
            fid_str = str(fact.fact_id)
            reasons = mandatory_reasons.get(fid_str, [])
            chrono_reasons = [r for r in reasons if r.startswith("chronology_")]
            if chrono_reasons:
                chronology_refs.append(
                    ChronologyReference(
                        profile_version=snapshot.profile_version,
                        fact_id=fact.fact_id,
                        kind=fact.kind,
                        title=fact.title,
                        start_date=fact.start_date,
                        end_date=fact.end_date,
                        reason=chrono_reasons[0],
                    )
                )

        # 8. Copy explicit eligibility faithfully
        detached_eligibility = CandidateEligibility.model_validate(
            snapshot.explicit_eligibility.model_dump(mode="python")
        )

        # 9. Return detached PreparedProfileContext
        # Ensure mandatory_fact_ids follows view.mandatory_facts ordering
        ordered_mandatory_ids = [f.fact_id for f in view.mandatory_facts]

        return PreparedProfileContext(
            candidate_id=snapshot.candidate_id,
            profile_version=snapshot.profile_version,
            purpose=purpose,
            inclusion_rule_version=self.inclusion_rule_version,
            mandatory_policy_version=self.mandatory_policy_version,
            eligible_facts=[
                CandidateFact.model_validate(f.model_dump(mode="python"))
                for f in view.eligible_facts
            ],
            eligible_fact_ids=list(view.eligible_fact_ids),
            mandatory_facts=[
                CandidateFact.model_validate(f.model_dump(mode="python"))
                for f in view.mandatory_facts
            ],
            mandatory_fact_ids=ordered_mandatory_ids,
            mandatory_reasons=mandatory_reasons,
            chronology=chronology_refs,
            explicit_eligibility=detached_eligibility,
            eligibility_source=f"{snapshot.profile_version}#explicit_eligibility",
            excluded_fact_count=view.excluded_fact_count,
            warnings=list(view.warnings),
        )
