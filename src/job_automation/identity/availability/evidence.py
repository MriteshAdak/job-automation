"""Evidence qualification and manifest fingerprinting (IDENTITY-02-S02).

Enforces:
- Negative evidence (disappearance inference) is ONLY permitted from authoritative
  COMPLETE inventories with COMPLETE_BOARD semantics.
- Partial, failed, search-only, and filtered feeds strictly block disappearance inference.
- Deterministic manifest content fingerprinting.
"""

from __future__ import annotations

import hashlib
import json

from job_automation.contracts.enums import FetchOutcome, InventorySemantics
from job_automation.contracts.postings import FetchManifest


def is_manifest_eligible_for_negative_inference(
    manifest: FetchManifest,
) -> tuple[bool, str | None]:
    """Evaluate whether a C04 FetchManifest supports negative disappearance inference.

    Returns:
        tuple[bool, str | None]: (is_eligible, blocked_reason)
    """
    if manifest.outcome != FetchOutcome.COMPLETE:
        return (
            False,
            f"Manifest outcome is '{manifest.outcome.value}'; incomplete/failed fetches cannot prove absence",
        )

    if manifest.inventory_semantics != InventorySemantics.COMPLETE_BOARD:
        return (
            False,
            f"Inventory semantics '{manifest.inventory_semantics.value}' does not provide negative evidence",
        )

    if manifest.error is not None:
        return (
            False,
            f"Manifest contains classified error '{manifest.error.category.value}'; negative evidence blocked",
        )

    if manifest.start_time > manifest.end_time:
        return (
            False,
            "Manifest start_time is later than end_time; invalid chronology blocks negative inference",
        )

    if not manifest.scope_id or not manifest.scope_id.strip():
        return (
            False,
            "Manifest scope_id is missing or empty; un-scoped manifests cannot establish absence",
        )

    return (True, None)


def compute_manifest_fingerprint(manifest: FetchManifest) -> str:
    """Compute a deterministic SHA-256 fingerprint for a manifest's content."""
    payload = {
        "run_id": str(manifest.run_id),
        "source_key": manifest.source_key,
        "scope_id": manifest.scope_id,
        "start_time": manifest.start_time.isoformat(),
        "end_time": manifest.end_time.isoformat(),
        "outcome": manifest.outcome.value,
        "inventory_semantics": manifest.inventory_semantics.value,
        "page_count": manifest.page_count,
        "observed_posting_identities": sorted(manifest.observed_posting_identities),
    }
    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return f"sha256:{digest}"

