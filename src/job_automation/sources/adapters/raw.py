"""Raw payload capture capability and content hashing (SOURCE-02-S03).

Provides the capture sink protocol, exact-byte content hashing, and in-memory sink.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Protocol, runtime_checkable

from job_automation.contracts.primitives import ContentHash


def compute_content_hash(content_bytes: bytes) -> str:
    """Compute the SHA-256 ContentHash string from exact bytes."""
    hex_digest = hashlib.sha256(content_bytes).hexdigest()
    return f"sha256:{hex_digest}"


def verify_content_hash(content_bytes: bytes, expected_hash: str) -> bool:
    """Verify exact bytes match an expected ContentHash."""
    return compute_content_hash(content_bytes) == expected_hash


@runtime_checkable
class RawCaptureSink(Protocol):
    """Protocol for retaining exact bytes and returning an immutable reference and hash."""

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        """Capture content bytes and return (raw_payload_ref, raw_content_hash).

        Raises an operational exception if capture fails.
        """
        ...

    def get(self, raw_payload_ref: str) -> bytes | None:
        """Retrieve previously captured content bytes by reference."""
        ...


class InMemoryRawCaptureSink:
    """Deterministic in-memory capture sink for testing and standalone processing."""

    def __init__(self) -> None:
        self._storage: dict[str, bytes] = {}

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        content_hash = compute_content_hash(content_bytes)
        token = uuid.uuid4().hex[:12]
        hint = f"{identifier_hint.strip()}_" if identifier_hint.strip() else ""
        ref = f"memory://{hint}{token}"
        self._storage[ref] = content_bytes
        return ref, content_hash

    def get(self, raw_payload_ref: str) -> bytes | None:
        return self._storage.get(raw_payload_ref)

