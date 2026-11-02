"""Flat binary packed vector matrix serialization and read access."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Sequence

from job_automation.context.index_errors import (
    IndexCorruptionError,
    IndexValidationError,
)
from job_automation.contracts.retrieval_index import PayloadFileInfo


class VectorMatrixWriter:
    """Writes contiguous, little-endian float32 vector matrices to disk."""

    def __init__(
        self,
        dest_path: Path,
        dimension: int,
        dtype: str = "float32",
        byte_order: str = "little_endian",
    ) -> None:
        self.dest_path = dest_path
        self.dimension = dimension
        self.dtype = dtype
        self.byte_order = byte_order

    def write_matrix(
        self,
        vectors: Sequence[Sequence[float]],
        relative_to: Path | None = None,
    ) -> PayloadFileInfo:
        """Write all vectors as contiguous little-endian float32 binary rows."""
        self.dest_path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        total_bytes = 0

        fmt = f"<{self.dimension}f"
        expected_row_bytes = self.dimension * 4

        with open(self.dest_path, "wb") as f:
            for row_idx, vec in enumerate(vectors):
                if len(vec) != self.dimension:
                    raise IndexValidationError(
                        f"Row {row_idx} length {len(vec)} != dimension {self.dimension}",
                        field_path=f"vectors[{row_idx}]",
                    )
                packed = struct.pack(fmt, *vec)
                f.write(packed)
                h.update(packed)
                total_bytes += expected_row_bytes

        rel_path = (
            self.dest_path.relative_to(relative_to).as_posix()
            if relative_to is not None
            else self.dest_path.name
        )
        return PayloadFileInfo(
            relative_path=rel_path,
            byte_length=total_bytes,
            sha256_hash=h.hexdigest(),
        )


class VectorMatrixReader:
    """Reads slices or individual rows from a packed vector matrix."""

    def __init__(self, path: Path, row_count: int, dimension: int) -> None:
        self.path = path
        self.row_count = row_count
        self.dimension = dimension
        self.row_bytes = dimension * 4

        # Verify on-disk file size matches exact expected byte count
        expected_total_bytes = row_count * self.row_bytes
        if not path.is_file():
            raise IndexCorruptionError(
                f"Vector matrix file missing: {path}",
                artifact="vectors.bin",
            )
        actual_size = path.stat().st_size
        if actual_size != expected_total_bytes:
            raise IndexCorruptionError(
                f"Vector matrix size mismatch: expected {expected_total_bytes} bytes, got {actual_size} bytes",
                artifact="vectors.bin",
                details={"expected_bytes": expected_total_bytes, "actual_bytes": actual_size},
            )

    def read_vector(self, row_ordinal: int) -> list[float]:
        """Read single vector by 0-based row ordinal."""
        if not (0 <= row_ordinal < self.row_count):
            raise IndexError(f"Row ordinal {row_ordinal} out of range [0, {self.row_count})")

        offset = row_ordinal * self.row_bytes
        with open(self.path, "rb") as f:
            f.seek(offset)
            data = f.read(self.row_bytes)
        return list(struct.unpack(f"<{self.dimension}f", data))

    def read_vectors(
        self,
        row_ordinals: Sequence[int] | None = None,
    ) -> list[list[float]]:
        """Read multiple vectors in order (or all if None)."""
        if row_ordinals is None:
            if self.row_count == 0:
                return []
            with open(self.path, "rb") as f:
                data = f.read()
            fmt = f"<{self.dimension}f"
            return [
                list(struct.unpack_from(fmt, data, i * self.row_bytes))
                for i in range(self.row_count)
            ]

        results: list[list[float]] = []
        with open(self.path, "rb") as f:
            for ord_val in row_ordinals:
                if not (0 <= ord_val < self.row_count):
                    raise IndexError(f"Row ordinal {ord_val} out of range [0, {self.row_count})")
                f.seek(ord_val * self.row_bytes)
                data = f.read(self.row_bytes)
                results.append(list(struct.unpack(f"<{self.dimension}f", data)))
        return results

