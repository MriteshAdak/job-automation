"""Bulky evidence file storage beneath profiles_dir.

Handles content-addressable storage, atomic staging, Windows path sanitization,
and strict directory traversal prevention.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from job_automation.profile.errors import EvidenceStoreError

_WINDOWS_RESERVED_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(filename: str) -> str:
    """Sanitize filename for Windows filesystem and prevent path traversal."""
    # Strip any directory components
    name = Path(filename).name
    # Replace reserved characters
    sanitized = _WINDOWS_RESERVED_CHARS.sub("_", name)
    sanitized = sanitized.strip(". ")
    if not sanitized:
        sanitized = f"evidence_{uuid.uuid4().hex[:8]}"
    return sanitized


class EvidenceStore:
    """Manages storage of bulky evidence files beneath profiles_dir."""

    def __init__(self, profiles_dir: Path | str) -> None:
        self.profiles_dir = Path(profiles_dir).resolve()

    def _ensure_within_root(self, target_path: Path) -> Path:
        """Verify that target_path resolves strictly within profiles_dir."""
        try:
            resolved = target_path.resolve()
            if self.profiles_dir != resolved and self.profiles_dir not in resolved.parents:
                raise EvidenceStoreError(
                    f"Path traversal detected: path '{target_path}' escapes profiles directory"
                )
            return resolved
        except (ValueError, RuntimeError) as err:
            raise EvidenceStoreError(f"Invalid path traversal attempt: {err}") from err

    def save_evidence_file(
        self,
        candidate_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, str]:
        """Save evidence file safely with atomic staging and return (relative_path, sha256_hash)."""
        safe_name = sanitize_filename(filename)
        sha256_digest = hashlib.sha256(content).hexdigest()
        content_hash = f"sha256:{sha256_digest}"

        staging_dir = self.profiles_dir / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        temp_file = staging_dir / f"tmp_{uuid.uuid4().hex}_{safe_name}"

        try:
            temp_file.write_bytes(content)

            # Target directory: profiles_dir / <candidate_id>
            dest_dir = self.profiles_dir / str(candidate_id)
            dest_dir.mkdir(parents=True, exist_ok=True)

            dest_filename = f"{sha256_digest[:12]}_{safe_name}"
            dest_path = dest_dir / dest_filename
            self._ensure_within_root(dest_path)

            # Atomic replace/move
            if dest_path.exists():
                temp_file.unlink()
            else:
                temp_file.replace(dest_path)

            rel_path = dest_path.relative_to(self.profiles_dir).as_posix()
            return rel_path, content_hash

        except Exception as err:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            if isinstance(err, EvidenceStoreError):
                raise
            raise EvidenceStoreError(f"Failed to store evidence file '{safe_name}': {err}") from err

    def read_evidence_file(self, relative_path: str, expected_hash: str | None = None) -> bytes:
        """Read evidence file and verify hash integrity."""
        # Normalize slashes
        clean_rel = Path(relative_path)
        if clean_rel.is_absolute() or ".." in clean_rel.parts:
            raise EvidenceStoreError(f"Invalid relative path escaping root: '{relative_path}'")

        target_path = self.profiles_dir / clean_rel
        resolved = self._ensure_within_root(target_path)

        if not resolved.is_file():
            raise EvidenceStoreError(f"Evidence file not found: '{relative_path}'")

        content = resolved.read_bytes()

        if expected_hash is not None:
            actual_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
            if actual_hash != expected_hash:
                raise EvidenceStoreError(
                    f"Evidence file integrity check failed: expected {expected_hash}, got {actual_hash}"
                )

        return content

    def has_evidence_file(self, relative_path: str) -> bool:
        """Check if an evidence file exists beneath profiles_dir."""
        try:
            clean_rel = Path(relative_path)
            if clean_rel.is_absolute() or ".." in clean_rel.parts:
                return False
            target_path = self._ensure_within_root(self.profiles_dir / clean_rel)
            return target_path.is_file()
        except EvidenceStoreError:
            return False

