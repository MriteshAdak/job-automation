"""Unit tests for VectorMatrixWriter and VectorMatrixReader."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.context.index_errors import IndexCorruptionError
from job_automation.context.vector_matrix import (
    VectorMatrixReader,
    VectorMatrixWriter,
)


def test_vector_matrix_write_and_read_roundtrip(tmp_path: Path) -> None:
    dest = tmp_path / "vectors.bin"
    writer = VectorMatrixWriter(dest_path=dest, dimension=4)

    test_vectors = [
        [0.1, 0.2, 0.3, 0.4],
        [0.5, 0.6, 0.7, 0.8],
        [-0.1, -0.2, -0.3, -0.4],
    ]

    info = writer.write_matrix(test_vectors)
    assert info.byte_length == 3 * 4 * 4  # 3 rows, 4 floats, 4 bytes each = 48 bytes
    assert len(info.sha256_hash) == 64

    reader = VectorMatrixReader(path=dest, row_count=3, dimension=4)

    # Read single row
    v0 = reader.read_vector(0)
    for expected, actual in zip(test_vectors[0], v0):
        assert abs(expected - actual) < 1e-6

    v1 = reader.read_vector(1)
    for expected, actual in zip(test_vectors[1], v1):
        assert abs(expected - actual) < 1e-6

    # Read all rows
    all_rows = reader.read_vectors()
    assert len(all_rows) == 3

    # Slice reading
    sliced = reader.read_vectors([2, 0])
    assert len(sliced) == 2
    for expected, actual in zip(test_vectors[2], sliced[0]):
        assert abs(expected - actual) < 1e-6


def test_vector_matrix_corrupt_size_detected(tmp_path: Path) -> None:
    dest = tmp_path / "truncated_vectors.bin"
    # Write only 10 bytes instead of 48
    dest.write_bytes(b"0123456789")

    with pytest.raises(IndexCorruptionError) as exc:
        VectorMatrixReader(path=dest, row_count=3, dimension=4)
    assert "Vector matrix size mismatch" in exc.value.message

