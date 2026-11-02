"""Profile version history querying and structural diff calculation."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Sequence

from job_automation.contracts.profile import CandidateFact, ProfileSnapshot
from job_automation.profile.models import (
    FactDiff,
    ProfileDiff,
    ProfileVersionRecord,
)

if TYPE_CHECKING:
    from job_automation.storage.repositories.profiles import ProfileRepository


def compare_snapshots(base: ProfileSnapshot, target: ProfileSnapshot) -> ProfileDiff:
    """Compute structural diff between two ProfileSnapshots by stable fact_id."""
    base_facts = {f.fact_id: f for f in base.evidence_records}
    target_facts = {f.fact_id: f for f in target.evidence_records}

    added: list[CandidateFact] = []
    removed: list[CandidateFact] = []
    updated: list[FactDiff] = []
    unchanged_ids: list[uuid.UUID] = []

    # Check target facts against base
    for fid, t_fact in target_facts.items():
        if fid not in base_facts:
            added.append(t_fact)
        else:
            b_fact = base_facts[fid]
            changed_fields: list[str] = []

            if t_fact.title != b_fact.title:
                changed_fields.append("title")
            if t_fact.organization != b_fact.organization:
                changed_fields.append("organization")
            if t_fact.kind != b_fact.kind:
                changed_fields.append("kind")
            if t_fact.start_date != b_fact.start_date:
                changed_fields.append("start_date")
            if t_fact.end_date != b_fact.end_date:
                changed_fields.append("end_date")
            if set(t_fact.claims) != set(b_fact.claims):
                changed_fields.append("claims")
            if set(t_fact.skills) != set(b_fact.skills):
                changed_fields.append("skills")
            if set(t_fact.metrics) != set(b_fact.metrics):
                changed_fields.append("metrics")
            if set(t_fact.allowed_uses) != set(b_fact.allowed_uses):
                changed_fields.append("allowed_uses")
            if t_fact.provenance != b_fact.provenance:
                changed_fields.append("provenance")

            if changed_fields:
                updated.append(
                    FactDiff(
                        fact_id=fid,
                        change_type="updated",
                        title=t_fact.title,
                        changed_fields=changed_fields,
                    )
                )
            else:
                unchanged_ids.append(fid)

    # Check for removed facts
    for fid, b_fact in base_facts.items():
        if fid not in target_facts:
            removed.append(b_fact)

    elig_changed = base.explicit_eligibility != target.explicit_eligibility

    return ProfileDiff(
        base_version=base.profile_version,
        target_version=target.profile_version,
        added_facts=added,
        removed_facts=removed,
        updated_facts=updated,
        unchanged_fact_ids=unchanged_ids,
        eligibility_changed=elig_changed,
    )


def list_version_history(
    repo: ProfileRepository,
    candidate_id: uuid.UUID | None = None,
) -> list[ProfileVersionRecord]:
    """Return ordered list of published version records."""
    return repo.get_version_history(candidate_id)
