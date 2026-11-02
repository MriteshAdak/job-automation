"""Deterministic canonical JSON serialization and fingerprinting for CONTEXT-01."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

from job_automation.context.records import PreparedProfileContext
from job_automation.contracts.profile import CandidateFact


def serialize_candidate_fact(fact: CandidateFact) -> dict[str, Any]:
    """Serialize every field of a permitted CandidateFact losslessly."""
    return {
        "fact_id": str(fact.fact_id),
        "parent_id": str(fact.parent_id) if fact.parent_id is not None else None,
        "kind": fact.kind.value,
        "title": fact.title,
        "organization": fact.organization,
        "start_date": fact.start_date.model_dump(mode="json") if fact.start_date else None,
        "end_date": fact.end_date.model_dump(mode="json") if fact.end_date else None,
        "skills": list(fact.skills),
        "claims": list(fact.claims),
        "metrics": [m.model_dump(mode="json") if hasattr(m, "model_dump") else str(m) for m in fact.metrics],
        "provenance": fact.provenance,
        "allowed_uses": list(fact.allowed_uses),
    }


def serialize_candidate_model_projection(prepared: PreparedProfileContext) -> str:
    """Serialize the candidate evidence universe into a deterministic model-facing JSON projection.

    Guarantees:
    - Complete representation of all permitted evidence records (no fields omitted).
    - Preserves exact array ordering of facts, skills, and claims.
    - Keys are deterministically sorted; separators are consistent.
    - Unicode characters (such as German umlauts) are preserved unescaped.
    """
    projection = {
        "candidate_id": str(prepared.candidate_id),
        "profile_version": prepared.profile_version,
        "purpose": prepared.purpose,
        "inclusion_rule_version": prepared.inclusion_rule_version,
        "mandatory_policy_version": prepared.mandatory_policy_version,
        "explicit_eligibility": prepared.explicit_eligibility.model_dump(mode="json"),
        "eligibility_source": prepared.eligibility_source,
        "chronology_anchors": [
            anchor.model_dump(mode="json") for anchor in prepared.chronology
        ],
        "facts": [serialize_candidate_fact(fact) for fact in prepared.eligible_facts],
    }

    return json.dumps(projection, indent=2, sort_keys=True, ensure_ascii=False)


def build_mandatory_context_strings(prepared: PreparedProfileContext) -> list[str]:
    """Build deterministic string representations for C09.mandatory_context compatibility.

    Maps explicit eligibility and chronology anchors into human-readable strings.
    """
    entries: list[str] = []

    # 1. Explicit eligibility entries
    elig = prepared.explicit_eligibility
    if elig.work_authorization_countries:
        countries = ", ".join(sorted(elig.work_authorization_countries))
        entries.append(f"Work authorization: {countries}")
    if elig.remote_eligible is not None:
        entries.append(f"Remote eligible: {elig.remote_eligible}")
    if elig.min_salary is not None:
        entries.append(f"Minimum salary expectation: {elig.min_salary.amount} {elig.min_salary.currency}")

    # 2. Chronology anchors
    for anchor in prepared.chronology:
        start_str = anchor.start_date.value if anchor.start_date else "Unknown"
        end_str = anchor.end_date.value if anchor.end_date else "Unknown"
        entries.append(
            f"Chronology [{start_str} - {end_str}]: {anchor.title} ({anchor.kind.value}, fact_id={anchor.fact_id})"
        )

    return entries


def compute_content_fingerprint(
    candidate_projection_json: str,
    canonical_job_id: uuid.UUID,
    posting_revision: str,
    purpose: str,
    builder_version: str,
    serialization_version: str,
    instruction_text: str = "",
    requirements: Sequence[str] | None = None,
) -> str:
    """Compute a reproducible SHA-256 fingerprint over all input components."""
    hasher = hashlib.sha256()

    hasher.update(b"context_builder_fingerprint_v1\n")
    hasher.update(f"canonical_job_id:{canonical_job_id}\n".encode("utf-8"))
    hasher.update(f"posting_revision:{posting_revision}\n".encode("utf-8"))
    hasher.update(f"purpose:{purpose}\n".encode("utf-8"))
    hasher.update(f"builder_version:{builder_version}\n".encode("utf-8"))
    hasher.update(f"serialization_version:{serialization_version}\n".encode("utf-8"))

    if instruction_text.strip():
        hasher.update(f"instruction_text:{instruction_text.strip()}\n".encode("utf-8"))

    if requirements:
        reqs_str = "\n".join(requirements)
        hasher.update(f"requirements:\n{reqs_str}\n".encode("utf-8"))

    hasher.update(f"candidate_json:\n{candidate_projection_json}\n".encode("utf-8"))

    return f"sha256:{hasher.hexdigest()}"
