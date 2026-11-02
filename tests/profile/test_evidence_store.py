"""Tests for EvidenceStore bulky file storage, staging, and path safety."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.profile.errors import EvidenceStoreError
from job_automation.profile.evidence_store import EvidenceStore, sanitize_filename


class TestEvidenceStore:
    def test_save_and_read_evidence_file(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        store = EvidenceStore(profiles_dir=profiles_dir)

        cid = uuid.uuid4()
        content = b"PDF-1.4 Evidence bytes for contract"
        rel_path, content_hash = store.save_evidence_file(cid, "contract 2024.pdf", content)

        assert content_hash.startswith("sha256:")
        assert store.has_evidence_file(rel_path) is True

        # Read back and verify hash
        read_bytes = store.read_evidence_file(rel_path, expected_hash=content_hash)
        assert read_bytes == content

    def test_hash_mismatch_raises_error(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        store = EvidenceStore(profiles_dir=profiles_dir)

        cid = uuid.uuid4()
        rel_path, _ = store.save_evidence_file(cid, "doc.txt", b"Original content")

        with pytest.raises(EvidenceStoreError, match="integrity check failed"):
            store.read_evidence_file(rel_path, expected_hash="sha256:0000000000000000")

    def test_path_traversal_prevention(self, tmp_path: Path) -> None:
        profiles_dir = tmp_path / "profiles"
        store = EvidenceStore(profiles_dir=profiles_dir)

        # Relative path with parent traversal
        with pytest.raises(EvidenceStoreError, match="Invalid relative path"):
            store.read_evidence_file("../outside.txt")

    def test_filename_sanitization(self) -> None:
        raw_name = 'my:bad*file<name>?|".pdf'
        sanitized = sanitize_filename(raw_name)
        assert ":" not in sanitized
        assert "*" not in sanitized
        assert "<" not in sanitized
        assert ">" not in sanitized
        assert "?" not in sanitized
        assert "|" not in sanitized
        assert sanitized.endswith(".pdf")

