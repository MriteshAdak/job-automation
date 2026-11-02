"""Tests for filesystem storage of bulky raw payloads and binary artifacts."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.storage.filestore import (
    Filestore,
    compute_sha256,
    sanitize_filename,
)


class TestFilestore:
    @pytest.fixture
    def filestore(self, tmp_path: Path) -> Filestore:
        raw_dir = tmp_path / "raw payloads"
        artifacts_dir = tmp_path / "rendered artifacts"
        return Filestore(raw_dir=raw_dir, artifacts_dir=artifacts_dir)

    def test_sanitize_filename_windows_reserved_chars(self) -> None:
        raw_name = 'test:job/id\\with*question?and<brackets>|"quote"'
        cleaned = sanitize_filename(raw_name)
        # None of the unsafe chars should remain
        for char in ': / \\ * ? < > | "'.split():
            assert char not in cleaned
        assert cleaned == "test_job_id_with_question_and_brackets___quote_"

    def test_compute_sha256_format(self) -> None:
        h = compute_sha256("test payload string")
        assert h.startswith("sha256:")
        assert len(h) == 7 + 64  # 'sha256:' + 64 hex characters

    def test_save_and_read_raw_payload(self, filestore: Filestore) -> None:
        payload_content = '{"job": "Senior Python Engineer", "salary": "€80.000 äöü"}'
        path_str, content_hash = filestore.save_raw_payload(
            provider="arbeitnow",
            board_id="engineering",
            source_posting_id="12345",
            payload=payload_content,
        )

        assert Path(path_str).is_file()
        assert Path(path_str).is_relative_to(filestore.raw_dir)
        assert content_hash == compute_sha256(payload_content)

        # Read back
        loaded = filestore.read_raw_payload(path_str)
        assert loaded == payload_content

    def test_save_and_read_binary_artifact(self, filestore: Filestore) -> None:
        req_id = uuid.uuid4()
        binary_docx = b"PK\x03\x04MockDocxFileContent\x00\x01\x02\x03"
        path_str, content_hash, size_bytes = filestore.save_artifact_file(
            request_id=req_id,
            filename="Lebenslauf_Max_Mustermann.docx",
            content=binary_docx,
        )

        assert Path(path_str).is_file()
        assert Path(path_str).is_relative_to(filestore.artifacts_dir)
        assert content_hash == compute_sha256(binary_docx)
        assert size_bytes == len(binary_docx)

        # Read back
        loaded = filestore.read_artifact_file(path_str)
        assert loaded == binary_docx

