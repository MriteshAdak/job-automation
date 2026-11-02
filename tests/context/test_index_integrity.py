"""Unit tests for payload integrity verification and corruption detection."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.index_errors import IndexCorruptionError
from job_automation.context.index_files import (
    CHUNKS_FILENAME,
    KEYWORDS_FILENAME,
    MANIFEST_FILENAME,
    VECTORS_FILENAME,
    compute_file_digest,
    verify_generation_files,
)
from job_automation.context.index_manifest import IndexManifestBuilder
from job_automation.contracts.retrieval_index import PayloadFileInfo
from tests.context.index_test_helpers import create_test_build_request


def test_payload_integrity_verification_success(tmp_path: Path) -> None:
    gen_dir = tmp_path / "good_gen"
    gen_dir.mkdir(parents=True)

    vec_path = gen_dir / VECTORS_FILENAME
    kw_path = gen_dir / KEYWORDS_FILENAME
    chk_path = gen_dir / CHUNKS_FILENAME

    vec_path.write_bytes(b"vectors_payload")
    kw_path.write_bytes(b"keywords_payload")
    chk_path.write_bytes(b"chunks_payload")

    files = {
        "vectors": compute_file_digest(vec_path, relative_to=gen_dir),
        "keywords": compute_file_digest(kw_path, relative_to=gen_dir),
        "chunks": compute_file_digest(chk_path, relative_to=gen_dir),
    }

    req = create_test_build_request()
    manifest = IndexManifestBuilder.build_manifest(uuid.uuid4(), req, [], files)

    # Should pass without error
    verify_generation_files(gen_dir, manifest)


def test_payload_integrity_missing_file_raises(tmp_path: Path) -> None:
    gen_dir = tmp_path / "missing_file_gen"
    gen_dir.mkdir(parents=True)

    files = {
        "vectors": PayloadFileInfo(relative_path=VECTORS_FILENAME, byte_length=10, sha256_hash="0" * 64),
    }

    req = create_test_build_request()
    manifest = IndexManifestBuilder.build_manifest(uuid.uuid4(), req, [], files)

    with pytest.raises(IndexCorruptionError) as exc:
        verify_generation_files(gen_dir, manifest)
    assert "payload file missing" in exc.value.message


def test_payload_integrity_size_mismatch_raises(tmp_path: Path) -> None:
    gen_dir = tmp_path / "size_mismatch_gen"
    gen_dir.mkdir(parents=True)

    vec_path = gen_dir / VECTORS_FILENAME
    vec_path.write_bytes(b"short")  # 5 bytes

    files = {
        "vectors": PayloadFileInfo(relative_path=VECTORS_FILENAME, byte_length=100, sha256_hash="0" * 64),
    }

    req = create_test_build_request()
    manifest = IndexManifestBuilder.build_manifest(uuid.uuid4(), req, [], files)

    with pytest.raises(IndexCorruptionError) as exc:
        verify_generation_files(gen_dir, manifest)
    assert "size mismatch" in exc.value.message


def test_payload_integrity_hash_mismatch_raises(tmp_path: Path) -> None:
    gen_dir = tmp_path / "tampered_gen"
    gen_dir.mkdir(parents=True)

    vec_path = gen_dir / VECTORS_FILENAME
    vec_path.write_bytes(b"tampered content")

    files = {
        "vectors": PayloadFileInfo(
            relative_path=VECTORS_FILENAME,
            byte_length=len(b"tampered content"),
            sha256_hash="f" * 64,  # wrong hash
        ),
    }

    req = create_test_build_request()
    manifest = IndexManifestBuilder.build_manifest(uuid.uuid4(), req, [], files)

    with pytest.raises(IndexCorruptionError) as exc:
        verify_generation_files(gen_dir, manifest)
    assert "hash mismatch" in exc.value.message

