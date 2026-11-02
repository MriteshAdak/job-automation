"""Whole-input identity and canonical assessment fingerprinting (MATCH-02-S03)."""

from __future__ import annotations

import hashlib
import json
from typing import Union

from job_automation.assessment.llm_records import AssessmentRequest, RequirementSet
from job_automation.contracts.policy import SearchPolicy
from job_automation.policy.models import EffectivePolicy


def compute_assessment_input_fingerprint(
    request: AssessmentRequest,
    requirement_set: RequirementSet,
) -> str:
    """Compute canonical SHA-256 fingerprint over all output-affecting inputs and settings.

    Excludes attempt execution UUIDs, timestamps, and latency so identical inputs
    produce identical stable fingerprints. Changing any material input changes the fingerprint.
    """
    policy_ver = (
        request.policy.policy.policy_version
        if isinstance(request.policy, EffectivePolicy)
        else request.policy.policy_version
    )

    retrieval_fp = None
    if request.retrieval_settings is not None:
        retrieval_fp = request.retrieval_settings.compute_settings_fingerprint()

    payload = {
        "canonical_job_id": str(request.canonical_job_id),
        "posting_revision": request.posting_revision,
        "raw_content_hash": request.posting.raw_content_hash,
        "profile_version": request.profile.profile_version,
        "profile_digest": (
            getattr(request.profile.approval_metadata, "profile_digest", "")
            if hasattr(request.profile, "approval_metadata") and request.profile.approval_metadata
            else getattr(request.profile, "profile_digest", "")
        ),
        "policy_version": policy_ver,
        "context_strategy": str(request.context_strategy),
        "purpose": request.purpose,
        "requirement_set_fingerprint": requirement_set.fingerprint,
        "deterministic_trace_digest": request.deterministic_trace.compute_digest(),
        "model_identifier": request.model_identifier,
        "model_digest": request.model_digest or "",
        "prompt_version": request.prompt_version,
        "schema_version": request.schema_version,
        "context_limit": request.limits.context_limit,
        "output_reserve": request.limits.output_reserve,
        "safety_allowance": request.limits.safety_allowance,
        "retrieval_settings_fingerprint": retrieval_fp or "",
        "inclusion_rule_version": request.inclusion_rule_version,
        "mandatory_policy_version": request.mandatory_policy_version,
        "extractor_mode": request.extractor_mode,
    }

    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"
