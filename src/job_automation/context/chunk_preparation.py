"""Evidence and ancestor preparation for CONTEXT-02 evidence chunking.

Prepares permitted candidate facts and traceable ancestor context:
- Applies purpose filtering via shared InclusionRules.
- Preserves shared fact ordering (start_date descending, nulls last, UUID tie-break).
- Resolves full permitted ancestor chains without arbitrary depth truncation.
- Detects required restricted parents and raises ChunkPermissionError.
- Retains opaque parent references for optional restricted parents with explicit contextual limitations.
- Computes effective allowed uses as intersection of primary and ancestor permissions.
- Computes dependency fingerprints for all contributing facts.
- Defensively detaches all data structures.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.chunk_errors import (
    ChunkPermissionError,
    ChunkValidationError,
)
from job_automation.context.chunk_identity import compute_fact_dependency_fingerprint
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    ChunkingSettings,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact, ProfileSnapshot
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


class PreparedChunkFact:
    """Prepared primary fact with resolved permitted ancestors, permissions, and dependencies."""

    def __init__(
        self,
        primary_fact: CandidateFact,
        ancestors: list[AncestorContext],
        effective_allowed_uses: list[str],
        dependency_fingerprints: dict[str, str],
        contextual_limitations: list[str],
    ) -> None:
        self.primary_fact = primary_fact
        self.ancestors = ancestors
        self.effective_allowed_uses = effective_allowed_uses
        self.dependency_fingerprints = dependency_fingerprints
        self.contextual_limitations = contextual_limitations


class PreparedChunkData:
    """Complete prepared evidence universe for chunk creation."""

    def __init__(
        self,
        snapshot: ProfileSnapshot,
        purpose: str,
        settings: ChunkingSettings,
        prepared_facts: list[PreparedChunkFact],
        eligible_fact_ids: list[uuid.UUID],
        excluded_fact_count: int,
        warnings: list[str],
    ) -> None:
        self.snapshot = snapshot
        self.purpose = purpose
        self.settings = settings
        self.prepared_facts = prepared_facts
        self.eligible_fact_ids = eligible_fact_ids
        self.excluded_fact_count = excluded_fact_count
        self.warnings = warnings


class ChunkEvidencePreparer:
    """Prepares permitted candidate facts and structured ancestor context."""

    def __init__(self, rule_version: str = DEFAULT_RULE_VERSION) -> None:
        self.rule_version = rule_version
        self._inclusion_rules = InclusionRules(rule_version=rule_version)

    def prepare(
        self,
        snapshot: ProfileSnapshot,
        purpose: str,
        settings: ChunkingSettings,
        explicit_required_fact_ids: Sequence[uuid.UUID] | None = None,
    ) -> PreparedChunkData:
        """Validate snapshot and prepare permitted facts with ancestor anchors."""
        # 1. Validate snapshot invariants
        try:
            validate_snapshot(snapshot)
        except ProfileValidationError as exc:
            raise ChunkValidationError(
                f"Invalid profile snapshot: {str(exc)}",
                field_path=exc.field_path,
                code=exc.code,
            ) from exc

        # 2. Validate purpose
        if purpose not in SUPPORTED_PURPOSES:
            raise ChunkValidationError(
                f"Unsupported inclusion purpose '{purpose}'. Must be one of {sorted(SUPPORTED_PURPOSES)}",
                field_path="purpose",
                code="UNSUPPORTED_PURPOSE",
            )

        fact_map = {f.fact_id: f for f in snapshot.evidence_records}

        # 3. Check explicit required fact IDs
        required_ids = list(explicit_required_fact_ids or [])
        for fid in required_ids:
            if fid not in fact_map:
                raise ChunkValidationError(
                    f"Required fact '{fid}' not found in profile snapshot",
                    field_path="explicit_required_fact_ids",
                    code="MANDATORY_FACT_NOT_FOUND",
                )

        permitted_ids: set[uuid.UUID] = set()
        for fact in snapshot.evidence_records:
            if fact.allowed_uses and purpose in fact.allowed_uses:
                permitted_ids.add(fact.fact_id)

        for fid in required_ids:
            if fid not in permitted_ids:
                raise ChunkPermissionError(
                    f"Required fact '{fid}' is restricted from purpose '{purpose}'",
                    field_path=f"facts[{fid}].allowed_uses",
                    details={"fact_id": str(fid), "purpose": purpose},
                )

        # 4. Evaluate inclusion via shared InclusionRules
        try:
            view: ProfileInclusionView = self._inclusion_rules.evaluate_inclusion(
                snapshot=snapshot,
                purpose=purpose,
                mandatory_fact_ids=required_ids,
            )
        except InclusionConflictError as exc:
            raise ChunkPermissionError(
                str(exc),
                field_path="explicit_required_fact_ids",
            ) from exc
        except ProfileValidationError as exc:
            raise ChunkValidationError(
                str(exc),
                field_path=exc.field_path,
                code=exc.code,
            ) from exc

        # 5. Resolve ancestor chains for each eligible fact
        prepared_facts: list[PreparedChunkFact] = []
        combined_warnings = list(view.warnings)

        for fact in view.eligible_facts:
            # Defensively detach primary fact
            detached_fact = CandidateFact.model_validate(fact.model_dump(mode="python"))

            ancestors: list[AncestorContext] = []
            contributing_facts: list[CandidateFact] = [detached_fact]
            contextual_limitations: list[str] = []

            curr_parent_id = detached_fact.parent_id
            visited: set[uuid.UUID] = {detached_fact.fact_id}

            while curr_parent_id is not None:
                if curr_parent_id in visited:
                    break
                visited.add(curr_parent_id)

                p_fact = fact_map.get(curr_parent_id)
                if p_fact is None:
                    raise ChunkValidationError(
                        f"Parent fact '{curr_parent_id}' of fact '{detached_fact.fact_id}' not found in snapshot",
                        field_path=f"facts[{detached_fact.fact_id}].parent_id",
                    )

                is_permitted = bool(p_fact.allowed_uses and purpose in p_fact.allowed_uses)
                if is_permitted:
                    detached_parent = CandidateFact.model_validate(p_fact.model_dump(mode="python"))
                    contributing_facts.append(detached_parent)
                    anc_context = AncestorContext(
                        fact_id=detached_parent.fact_id,
                        kind=detached_parent.kind,
                        title=detached_parent.title,
                        organization=detached_parent.organization,
                        start_date=detached_parent.start_date,
                        end_date=detached_parent.end_date,
                        parent_id=detached_parent.parent_id,
                        provenance=detached_parent.provenance,
                        allowed_uses=list(detached_parent.allowed_uses or []),
                    )
                    ancestors.append(anc_context)
                    curr_parent_id = detached_parent.parent_id
                else:
                    # Parent is restricted
                    if settings.strict_parents or (curr_parent_id in required_ids):
                        raise ChunkPermissionError(
                            f"Required parent fact '{curr_parent_id}' of fact '{detached_fact.fact_id}' is restricted from purpose '{purpose}'",
                            field_path=f"facts[{curr_parent_id}].allowed_uses",
                            details={
                                "fact_id": str(detached_fact.fact_id),
                                "parent_id": str(curr_parent_id),
                                "purpose": purpose,
                            },
                        )

                    # Optional parent under default policy:
                    # Opaque reference retained; restricted text omitted; explicit limitation recorded
                    limitation_msg = f"restricted_parent_omitted:{curr_parent_id}"
                    if limitation_msg not in contextual_limitations:
                        contextual_limitations.append(limitation_msg)

                    warn_msg = f"Parent fact '{curr_parent_id}' of fact '{detached_fact.fact_id}' is restricted and omitted from '{purpose}' view"
                    if warn_msg not in combined_warnings:
                        combined_warnings.append(warn_msg)
                    break

            # Reverse ancestors so root ancestor is first: [root, ..., immediate_parent]
            ancestors_root_first = list(reversed(ancestors))

            # Effective allowed uses = intersection of all contributing facts
            effective_uses = set(detached_fact.allowed_uses or [])
            for anc in ancestors:
                effective_uses = effective_uses.intersection(set(anc.allowed_uses))
            sorted_effective_uses = sorted(effective_uses)

            # Compute dependency fingerprints for all contributing facts
            dep_fingerprints: dict[str, str] = {}
            for c_fact in contributing_facts:
                dep_fingerprints[str(c_fact.fact_id)] = compute_fact_dependency_fingerprint(c_fact)

            prepared_facts.append(
                PreparedChunkFact(
                    primary_fact=detached_fact,
                    ancestors=ancestors_root_first,
                    effective_allowed_uses=sorted_effective_uses,
                    dependency_fingerprints=dep_fingerprints,
                    contextual_limitations=contextual_limitations,
                )
            )

        combined_warnings.sort()

        return PreparedChunkData(
            snapshot=snapshot,
            purpose=purpose,
            settings=settings,
            prepared_facts=prepared_facts,
            eligible_fact_ids=list(view.eligible_fact_ids),
            excluded_fact_count=view.excluded_fact_count,
            warnings=combined_warnings,
        )

