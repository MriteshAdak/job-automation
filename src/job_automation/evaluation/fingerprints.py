"""Deterministic SHA-256 fingerprinting for evaluation records and manifests (EVAL-01-S01).

Enforces:
- Canonical JSON formatting (UTF-8, sorted keys, no whitespace separators).
- Strict hash prefixing ('sha256:').
- Content-based equality for experiment manifests, case definitions, and gold labels.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence


def canonical_json_bytes(obj: Any) -> bytes:
    """Serialize a Python object or dict to canonical JSON bytes."""
    def _default_serializer(o: Any) -> Any:
        if hasattr(o, "model_dump"):
            return o.model_dump(mode="json")
        if hasattr(o, "isoformat"):
            return o.isoformat()
        if hasattr(o, "value"):
            return o.value
        return str(o)

    dumped = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        default=_default_serializer,
        ensure_ascii=False,
    )
    return dumped.encode("utf-8")


def compute_sha256(data: bytes | str) -> str:
    """Compute sha256 hex digest prefixed with 'sha256:'."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def compute_canonical_fingerprint(obj: Any) -> str:
    """Compute sha256 of canonical JSON bytes representation of obj."""
    return compute_sha256(canonical_json_bytes(obj))


def compute_frame_hash(case_ids: Sequence[str]) -> str:
    """Compute stable frame hash for an ordered sequence of case IDs."""
    sorted_ids = sorted(case_ids)
    return compute_canonical_fingerprint(sorted_ids)

