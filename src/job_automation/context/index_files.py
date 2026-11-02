"""File management and payload verification for index generation directories on disk."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import NamedTuple

from job_automation.context.index_capacity import validate_index_path
from job_automation.context.index_errors import (
    IndexCorruptionError,
    IndexStorageError,
)
from job_automation.contracts.retrieval_index import (
    IndexManifest,
    PayloadFileInfo,
)

VECTORS_FILENAME = "vectors.bin"
KEYWORDS_FILENAME = "keywords.db"
CHUNKS_FILENAME = "chunks.json"
MANIFEST_FILENAME = "manifest.json"


class GenerationPaths(NamedTuple):
    """File paths for an index generation."""

    generation_dir: Path
    manifest_path: Path
    vectors_path: Path
    keywords_path: Path
    chunks_path: Path


def get_generation_dir(
    indexes_dir: Path | str,
    candidate_id: uuid.UUID,
    purpose: str,
    generation_id: uuid.UUID,
) -> Path:
    """Return canonical directory path for an index generation."""
    base = Path(indexes_dir)
    target = base / str(candidate_id) / purpose / str(generation_id)
    return validate_index_path(target, base)


def get_staging_dir(
    indexes_dir: Path | str,
    candidate_id: uuid.UUID,
    purpose: str,
    generation_id: uuid.UUID,
) -> Path:
    """Return staging directory path used during index construction."""
    base = Path(indexes_dir)
    target = base / str(candidate_id) / purpose / f"staging_{generation_id}"
    return validate_index_path(target, base)


def resolve_generation_paths(generation_dir: Path) -> GenerationPaths:
    """Resolve standard file paths within an index generation directory."""
    return GenerationPaths(
        generation_dir=generation_dir,
        manifest_path=generation_dir / MANIFEST_FILENAME,
        vectors_path=generation_dir / VECTORS_FILENAME,
        keywords_path=generation_dir / KEYWORDS_FILENAME,
        chunks_path=generation_dir / CHUNKS_FILENAME,
    )


def compute_file_digest(file_path: Path, relative_to: Path) -> PayloadFileInfo:
    """Compute exact byte length and SHA-256 hash of a file on disk."""
    if not file_path.is_file():
        raise IndexStorageError(f"File not found: {file_path}", operation="compute_file_digest")

    h = hashlib.sha256()
    size = 0
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            size += len(chunk)
            h.update(chunk)

    rel_path = file_path.relative_to(relative_to).as_posix()
    return PayloadFileInfo(
        relative_path=rel_path,
        byte_length=size,
        sha256_hash=h.hexdigest(),
    )


def verify_generation_files(generation_dir: Path, manifest: IndexManifest) -> None:
    """Verify that all payload files in manifest exist on disk and match exact hashes and sizes.

    Raises:
    - IndexCorruptionError if any file is missing, truncated, or tampered.
    """
    for key, expected_info in manifest.payload_files.items():
        file_path = generation_dir / expected_info.relative_path
        if not file_path.is_file():
            raise IndexCorruptionError(
                f"Index payload file missing: {expected_info.relative_path}",
                artifact=key,
                details={"expected_path": str(file_path)},
            )

        actual_info = compute_file_digest(file_path, relative_to=generation_dir)
        if actual_info.byte_length != expected_info.byte_length:
            raise IndexCorruptionError(
                f"Index payload size mismatch for {key}: expected {expected_info.byte_length} bytes, got {actual_info.byte_length} bytes",
                artifact=key,
                details={
                    "expected_bytes": expected_info.byte_length,
                    "actual_bytes": actual_info.byte_length,
                },
            )
        if actual_info.sha256_hash != expected_info.sha256_hash:
            raise IndexCorruptionError(
                f"Index payload hash mismatch for {key}: expected {expected_info.sha256_hash}, got {actual_info.sha256_hash}",
                artifact=key,
                details={
                    "expected_hash": expected_info.sha256_hash,
                    "actual_hash": actual_info.sha256_hash,
                },
            )


def finalize_staging_directory(staging_dir: Path, final_dir: Path) -> None:
    """Atomically move staging directory to final immutable generation directory."""
    if final_dir.exists():
        raise IndexStorageError(
            f"Final index directory already exists: {final_dir}",
            operation="finalize_staging",
        )
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(staging_dir, final_dir)
    except OSError as err:
        # Fallback for Windows cross-directory rename if needed
        try:
            shutil.move(str(staging_dir), str(final_dir))
        except Exception as exc:
            raise IndexStorageError(
                f"Failed to finalize index directory from {staging_dir} to {final_dir}: {exc}",
                operation="finalize_staging",
            ) from exc

