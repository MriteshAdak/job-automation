"""Fingerprinting and deterministic identity generation for AUTO-02.

Enforces two distinct fingerprints:
1. Decision-input fingerprint: binds assessment, C02 policy, availability, candidate control,
   and profile evidence explaining why an admission decision was reached.
2. Material generation fingerprint: binds output-affecting document generation inputs
   (posting content, profile facts, document variant, layout, recipe, formats) to identify
   equivalent generation work across runs.

Client request keys use the grammar: auto02:v1:<digest>.
Policy versions and attempt timestamps are explicitly excluded from material keys.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
)


def compute_decision_input_fingerprint(
    candidate: AutomaticDraftCandidate,
    policy: AutomaticDraftPolicy,
    engine_version: str = "1.0",
) -> str:
    """Compute deterministic SHA-256 fingerprint explaining an admission decision."""
    components: dict[str, Any] = {
        "engine_version": engine_version,
        "canonical_job_id": str(candidate.canonical_job_id),
        "posting_revision_hash": candidate.posting_revision_hash,
        "assessment_id": str(candidate.assessment_id),
        "assessment_input_fingerprint": candidate.assessment_input_fingerprint,
        "assessment_disposition": candidate.assessment_disposition.value,
        "assessment_method": candidate.assessment_method,
        "relevance_score": candidate.relevance_score,
        "search_policy_version": candidate.search_policy_version,
        "search_policy_hash": candidate.search_policy_hash,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "policy_content_hash": policy.policy_content_hash,
        "availability_status": candidate.availability_status.value,
        "candidate_application_state": candidate.candidate_application_state,
        "candidate_opted_out": candidate.candidate_opted_out,
        "profile_version": candidate.profile_version,
        "profile_digest": candidate.profile_digest,
        "identified_unknowns": sorted(candidate.identified_unknowns),
        "validation_issues": sorted(candidate.validation_issues),
        "rule_coverage_complete": candidate.rule_coverage_complete,
    }
    canonical_json = json.dumps(components, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compute_material_generation_fingerprint(
    candidate: AutomaticDraftCandidate,
    variant: DocumentVariantConfig,
) -> str:
    """Compute deterministic SHA-256 fingerprint identifying equivalent generation work.

    Excludes attempt UUIDs, timestamps, relevance scores, and automatic policy versions.
    """
    components: dict[str, Any] = {
        "salesforce_org_id": candidate.salesforce_org_id,
        "candidate_id": str(candidate.candidate_id),
        "canonical_job_id": str(candidate.canonical_job_id),
        "normalized_content_hash": candidate.normalized_content_hash,
        "profile_version": candidate.profile_version,
        "profile_digest": candidate.profile_digest,
        "document_type": variant.document_type.value,
        "target_language": variant.target_language,
        "template_id": variant.template_id,
        "context_strategy": variant.context_strategy.value,
        "formats": sorted(variant.formats),
        "content_specification": variant.content_specification,
        "layout_id": variant.layout_id,
        "layout_version": variant.layout_version,
        "recipe_id": variant.recipe_id,
        "recipe_version": variant.recipe_version,
    }
    canonical_json = json.dumps(components, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def derive_automatic_client_request_key(
    material_fingerprint: str,
    org_id: str,
    candidate_id: uuid.UUID,
    canonical_job_id: uuid.UUID,
    document_type: str,
) -> str:
    """Derive namespaced, stable client request key (auto02:v1:<digest>).

    Policy version is intentionally excluded so changing a policy label
    cannot defeat duplicate suppression for identical generation inputs.
    """
    scope_material = f"{org_id}:{candidate_id}:{canonical_job_id}:{document_type}:{material_fingerprint}"
    digest = hashlib.sha256(scope_material.encode("utf-8")).hexdigest()[:32]
    return f"auto02:v1:{digest}"


def compute_payload_digest(payload: dict[str, Any]) -> str:
    """Compute SHA-256 digest of immutable request creation parameters."""
    canonical = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

