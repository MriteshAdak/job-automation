"""Capacity estimation and preflight resource verification for retrieval index builds."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from job_automation.context.index_errors import (
    IndexCapacityError,
    IndexConfigurationError,
    IndexValidationError,
)
from job_automation.contracts.evidence_chunks import ChunkSet
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexSettings,
)


def estimate_matrix_bytes(row_count: int, dimension: int, dtype: str = "float32") -> int:
    """Calculate exact byte size of packed vector matrix."""
    if dtype != "float32":
        raise IndexConfigurationError(f"Unsupported matrix dtype '{dtype}'")
    bytes_per_element = 4
    return row_count * dimension * bytes_per_element


def estimate_build_staging_bytes(
    chunk_count: int,
    dimension: int,
    total_text_bytes: int,
) -> int:
    """Estimate disk/memory bytes required during build staging."""
    matrix_bytes = estimate_matrix_bytes(chunk_count, dimension)
    # Estimate: matrix bytes + chunks.json (~1.5x raw text) + keywords.db (~2.5x raw text) + headroom
    estimated_payload_bytes = matrix_bytes + int(total_text_bytes * 4.0) + 131072  # 128 KB base DB overhead
    return estimated_payload_bytes


def validate_index_path(target_path: Path | str, base_indexes_dir: Path | str) -> Path:
    r"""Validate that target_path resolves strictly within base_indexes_dir.

    Rejects:
    - Non-absolute paths
    - UNC / network paths (e.g. \\server\share or //server/share)
    - Directory traversal or junction escapes targeting outside base_indexes_dir
    """
    base = Path(base_indexes_dir).resolve()
    target = Path(target_path)

    # Reject UNC paths
    target_str = str(target)
    if target_str.startswith(("\\\\", "//")):
        raise IndexConfigurationError(f"UNC/network paths are not permitted for index storage: {target_str}")

    resolved_target = target.resolve()

    # Base must be an ancestor of resolved_target, or equal
    try:
        resolved_target.relative_to(base)
    except ValueError as err:
        raise IndexConfigurationError(
            f"Index path '{resolved_target}' escapes configured index directory '{base}'"
        ) from err

    # Ensure it is not the repository root
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    try:
        resolved_target.relative_to(repo_root)
        raise IndexConfigurationError(
            f"Index directory '{resolved_target}' cannot be inside repository '{repo_root}'"
        )
    except ValueError:
        pass  # Expected: target is outside repo root

    return resolved_target


def check_index_capacity_preflight(
    chunk_set: ChunkSet,
    config: EmbeddingConfiguration,
    settings: IndexSettings,
    destination_dir: Path | None = None,
) -> None:
    """Preflight capacity check enforcing declared finite limits before model invocation.

    Raises:
    - IndexCapacityError if chunks, dimension, text length, or estimated memory exceed ceilings.
    - IndexConfigurationError if settings or paths are invalid.
    """
    chunk_count = len(chunk_set.chunks)

    # 1. Chunk count limit
    if chunk_count > settings.max_chunks:
        raise IndexCapacityError(
            f"Chunk count {chunk_count} exceeds maximum allowed {settings.max_chunks}",
            field_path="chunk_set.chunks",
            details={"chunk_count": chunk_count, "max_chunks": settings.max_chunks},
        )

    # 2. Embedding dimension limit
    if config.dimension > settings.max_dimension:
        raise IndexCapacityError(
            f"Embedding dimension {config.dimension} exceeds maximum allowed {settings.max_dimension}",
            field_path="embedding_config.dimension",
            details={"dimension": config.dimension, "max_dimension": settings.max_dimension},
        )

    # 3. Individual chunk text limits
    total_text_bytes = 0
    for idx, chunk in enumerate(chunk_set.chunks):
        text_bytes = len(chunk.retrieval_text.encode("utf-8"))
        if text_bytes > settings.max_text_bytes:
            raise IndexCapacityError(
                f"Chunk {chunk.chunk_id} retrieval_text ({text_bytes} bytes) exceeds limit ({settings.max_text_bytes} bytes)",
                field_path=f"chunk_set.chunks[{idx}].retrieval_text",
                details={
                    "chunk_id": str(chunk.chunk_id),
                    "bytes": text_bytes,
                    "max_bytes": settings.max_text_bytes,
                },
            )
        total_text_bytes += text_bytes

    # 4. Working memory estimate check
    matrix_bytes = estimate_matrix_bytes(chunk_count, config.dimension, settings.dtype)
    estimated_staging_bytes = estimate_build_staging_bytes(chunk_count, config.dimension, total_text_bytes)
    estimated_memory = matrix_bytes + (total_text_bytes * 2)

    if estimated_memory > settings.max_build_memory_bytes:
        raise IndexCapacityError(
            f"Estimated build working memory ({estimated_memory} bytes) exceeds limit ({settings.max_build_memory_bytes} bytes)",
            field_path="settings.max_build_memory_bytes",
            details={
                "estimated_memory_bytes": estimated_memory,
                "max_build_memory_bytes": settings.max_build_memory_bytes,
            },
        )

    # 5. Disk space check if destination directory is provided
    if destination_dir is not None and destination_dir.exists():
        try:
            usage = shutil.disk_usage(destination_dir)
            # Require at least estimated staging bytes plus a 50MB safety margin
            required_free = estimated_staging_bytes + 52428800
            if usage.free < required_free:
                raise IndexCapacityError(
                    f"Insufficient free disk space: {usage.free} bytes available, {required_free} bytes required",
                    field_path="disk_space",
                    details={"available_bytes": usage.free, "required_bytes": required_free},
                )
        except OSError:
            pass  # Non-fatal if filesystem doesn't support statvfs/disk_usage
