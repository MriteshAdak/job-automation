"""Canonical input fingerprinting for reproducible inference (LLM-01-S03).

Provides deterministic canonical hashing over generation prompts and ordered
embedding texts. Any variation in text, whitespace, ordering, or system prompt
produces a distinct hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

FINGERPRINT_VERSION: str = "v1"
FINGERPRINT_ALGORITHM: str = "sha256"


def _canonical_sha256(payload: dict[str, Any]) -> str:
    """Encode payload to canonical JSON and compute sha256 hex digest."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{FINGERPRINT_ALGORITHM}:{digest}"


def compute_generation_fingerprint(prompt: str, system_prompt: str | None = None) -> str:
    """Compute canonical fingerprint for generation input."""
    payload = {
        "format_version": FINGERPRINT_VERSION,
        "operation": "generation",
        "prompt": prompt,
        "system_prompt": system_prompt,
    }
    return _canonical_sha256(payload)


def compute_embedding_fingerprint(texts: list[str]) -> str:
    """Compute canonical fingerprint for ordered embedding texts."""
    payload = {
        "format_version": FINGERPRINT_VERSION,
        "operation": "embedding",
        "texts": list(texts),
    }
    return _canonical_sha256(payload)

