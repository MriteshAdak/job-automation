"""Deterministic input fingerprinting for cache reuse and invalidation (RUN-01-S03, S06)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from job_automation.configuration import AppConfig
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.policy.models import EffectivePolicy


def compute_sha256_hex(data: bytes | str) -> str:
    """Compute standard SHA-256 hex string."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def canonical_json_dumps(obj: Any) -> str:
    """Serialize dictionary or model to canonical sorted compact JSON."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_app_config_fingerprint(config: AppConfig) -> str:
    """Compute deterministic fingerprint of application configuration."""
    data = config.model_dump(mode="json", exclude={"data_root"})
    return compute_sha256_hex(canonical_json_dumps(data))


def compute_policy_fingerprint(policy: SearchPolicy | EffectivePolicy) -> str:
    """Compute deterministic fingerprint of active search policy."""
    if hasattr(policy, "fingerprint") and policy.fingerprint:
        return str(policy.fingerprint)
    if hasattr(policy, "to_search_policy"):
        p = policy.to_search_policy()
        data = p.model_dump(mode="json")
    else:
        data = policy.model_dump(mode="json")
    return compute_sha256_hex(canonical_json_dumps(data))


def compute_profile_snapshot_fingerprint(profile: ProfileSnapshot) -> str:
    """Compute deterministic fingerprint of approved profile snapshot."""
    data = profile.model_dump(mode="json")
    return compute_sha256_hex(canonical_json_dumps(data))


def compute_stage_work_fingerprint(
    stage_name: str,
    work_key: str,
    inputs: dict[str, Any],
) -> str:
    """Compute composite input fingerprint for a stage work item."""
    composite = {
        "stage": stage_name,
        "key": work_key,
        "inputs": inputs,
    }
    return compute_sha256_hex(canonical_json_dumps(composite))


def compute_assessment_composite_fingerprint(
    revision_content_hash: str,
    profile_snapshot_hash: str,
    policy_fingerprint: str,
    assessment_mode: str,
    strategy: str | None = None,
    model_identifier: str | None = None,
    prompt_version: str | None = None,
) -> str:
    """Compute composite fingerprint covering all output-affecting assessment inputs."""
    payload = {
        "rev_hash": revision_content_hash,
        "prof_hash": profile_snapshot_hash,
        "pol_fp": policy_fingerprint,
        "mode": assessment_mode,
        "strat": strategy or "none",
        "model": model_identifier or "none",
        "prompt": prompt_version or "none",
    }
    return compute_sha256_hex(canonical_json_dumps(payload))

