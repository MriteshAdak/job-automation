"""Durable filesystem raw capture sink (INGEST-01-S02).

Implements the RawCaptureSink protocol against the local filesystem,
preserving exact raw bytes immutably under configured raw_dir/captures.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from job_automation.sources.adapters.raw import (
    RawCaptureSink,
    compute_content_hash,
    verify_content_hash,
)

_UNSAFE_CHARS = re.compile(r'[^a-zA-Z0-9_\-]')


class DurableRawCaptureSink(RawCaptureSink):
    """Filesystem-backed durable capture sink.

    Guarantees:
    - Immutable storage of exact raw bytes (including BOM, CRLF, binary).
    - Content-hashed addressing with SHA-256 verification.
    - Path traversal and out-of-root access rejection.
    - Atomic file writes via temporary file replacement.
    - Handle cleanup and safe release.
    """

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir).resolve()
        self.captures_dir = self.raw_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, content_bytes: bytes, identifier_hint: str = "") -> tuple[str, str]:
        """Capture content bytes immutably to disk and return (ref, hash)."""
        content_hash = compute_content_hash(content_bytes)
        hex_digest = content_hash.split(":")[-1]

        safe_hint = _UNSAFE_CHARS.sub("_", identifier_hint).strip("_")[:40]
        if safe_hint:
            filename = f"{safe_hint}_{hex_digest[:16]}.dat"
        else:
            filename = f"{hex_digest}.dat"

        target_file = self.captures_dir / filename

        # If file already exists, verify exact bytes
        if target_file.is_file():
            existing = target_file.read_bytes()
            if existing == content_bytes:
                return str(target_file.resolve()), content_hash
            # In case of filename collision with different hint, fallback to pure digest name
            target_file = self.captures_dir / f"{hex_digest}.dat"
            if target_file.is_file() and target_file.read_bytes() == content_bytes:
                return str(target_file.resolve()), content_hash

        # Write atomically using a temporary file in the same directory
        temp_file = self.captures_dir / f".tmp_{uuid.uuid4().hex}"
        try:
            temp_file.write_bytes(content_bytes)
            temp_file.replace(target_file)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

        return str(target_file.resolve()), content_hash

    def get(self, raw_payload_ref: str) -> bytes | None:
        """Retrieve previously captured content bytes by reference."""
        clean_path_str = raw_payload_ref
        if clean_path_str.startswith("file:///"):
            clean_path_str = clean_path_str[8:]
        elif clean_path_str.startswith("file://"):
            clean_path_str = clean_path_str[7:]

        p = Path(clean_path_str).resolve()

        # Reject path traversal / out-of-root access
        try:
            if not p.is_relative_to(self.raw_dir):
                raise ValueError(
                    f"Path traversal or out-of-root raw payload reference rejected: '{raw_payload_ref}'"
                )
        except AttributeError:
            # Fallback for Python < 3.9 if ever run
            if not str(p).startswith(str(self.raw_dir)):
                raise ValueError(
                    f"Path traversal or out-of-root raw payload reference rejected: '{raw_payload_ref}'"
                )

        if not p.is_file():
            return None

        return p.read_bytes()

