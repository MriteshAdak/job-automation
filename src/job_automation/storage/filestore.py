"""Filestore for large raw responses and rendered document artifacts.

Keeps bulky raw payload text and binary document artifacts (DOCX/PDF)
stored on the filesystem outside the SQLite database, referenced by
path and SHA-256 content hash (blueprint §4, §6/DATA-01).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path


_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize arbitrary strings for Windows filesystem path safety."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return cleaned.strip(" .") or "unnamed"


def compute_sha256(data: bytes | str) -> str:
    """Compute prefixed SHA-256 content hash matching ContentHash contract."""
    raw_bytes = data.encode("utf-8") if isinstance(data, str) else data
    hex_digest = hashlib.sha256(raw_bytes).hexdigest()
    return f"sha256:{hex_digest}"


class Filestore:
    """Manages raw payload and artifact files on disk beneath configured directories."""

    def __init__(self, raw_dir: Path | str, artifacts_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.artifacts_dir = Path(artifacts_dir)

    def save_raw_payload(
        self,
        provider: str,
        board_id: str,
        source_posting_id: str,
        payload: str | bytes,
        suffix: str = ".json",
    ) -> tuple[str, str]:
        """Save a raw posting payload to the raw storage directory.

        Returns:
            tuple of (absolute_local_path, content_hash)
        """
        raw_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
        content_hash = compute_sha256(raw_bytes)

        target_dir = self.raw_dir / sanitize_filename(provider) / sanitize_filename(board_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{sanitize_filename(source_posting_id)}{suffix}"
        target_path = target_dir / filename

        target_path.write_bytes(raw_bytes)
        return str(target_path.resolve()), content_hash

    def read_raw_payload(self, ref: str | Path) -> str:
        """Read raw payload text from storage reference path."""
        p = Path(ref)
        if not p.is_file():
            raise FileNotFoundError(f"Raw payload file not found: {p}")
        return p.read_text(encoding="utf-8", errors="replace")

    def save_artifact_file(
        self,
        request_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> tuple[str, str, int]:
        """Save a rendered binary artifact (DOCX/PDF) to artifacts directory.

        Returns:
            tuple of (absolute_local_path, content_hash, size_bytes)
        """
        content_hash = compute_sha256(content)
        size_bytes = len(content)

        target_dir = self.artifacts_dir / str(request_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / sanitize_filename(filename)
        target_path.write_bytes(content)

        return str(target_path.resolve()), content_hash, size_bytes

    def read_artifact_file(self, ref: str | Path) -> bytes:
        """Read binary artifact content from storage reference path."""
        p = Path(ref)
        if not p.is_file():
            raise FileNotFoundError(f"Artifact file not found: {p}")
        return p.read_bytes()

