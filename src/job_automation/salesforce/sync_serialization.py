"""SYNC-01 serialization and fingerprinting utilities (SYNC-01-S02).

Enforces:
- Deterministic canonical JSON serialization
- Step and plan fingerprint calculation
- Strict candidate field stripping / verification
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from job_automation.salesforce.sync_errors import SyncOwnershipError, SyncValidationError
from job_automation.salesforce.sync_settings import SyncMappingConfig


def serialize_canonical_json(data: Any) -> bytes:
    """Serialize dictionary or list to sorted canonical JSON bytes."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def calculate_step_fingerprint(
    target_object: str,
    external_id_field: str,
    external_id_value: str,
    sequence_number: int,
    payload: dict[str, Any],
) -> str:
    """Calculate deterministic SHA-256 fingerprint for a write step."""
    envelope = {
        "target_object": target_object,
        "external_id_field": external_id_field,
        "external_id_value": external_id_value,
        "sequence_number": sequence_number,
        "payload": payload,
    }
    raw = serialize_canonical_json(envelope)
    return hashlib.sha256(raw).hexdigest()


def calculate_plan_fingerprint(
    canonical_job_id: str,
    mapping_hash: str,
    step_fingerprints: list[str],
) -> str:
    """Calculate deterministic SHA-256 fingerprint for an entire SyncPlan."""
    envelope = {
        "canonical_job_id": canonical_job_id,
        "mapping_hash": mapping_hash,
        "step_fingerprints": sorted(step_fingerprints),
    }
    raw = serialize_canonical_json(envelope)
    return hashlib.sha256(raw).hexdigest()


def assert_no_candidate_fields(
    payload: dict[str, Any],
    config: SyncMappingConfig,
    context_desc: str = "outbound write",
) -> None:
    """Verify that no candidate-owned fields are present in an outbound payload dictionary."""
    candidate_set = {f.lower() for f in config.candidate_fields}
    payload_keys = {k.lower() for k in payload.keys()}

    collision = candidate_set.intersection(payload_keys)
    if collision:
        raise SyncOwnershipError(
            f"Candidate-owned field(s) {collision} illegally present in {context_desc} payload!"
        )

