"""Tests for source registry loading, envelope validation, and file handling (SOURCE-01-S02)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.sources.loader import load_source_registry

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sources"


class TestSourceRegistryLoading:
    def test_load_valid_registry(self) -> None:
        """Verify loading valid_registry.json succeeds with expected entry count."""
        path = FIXTURES_DIR / "valid_registry.json"
        envelope, issues = load_source_registry(path)
        assert envelope.schema_version == "1.0"
        assert len(envelope.sources) == 3
        keys = [s.source_key for s in envelope.sources]
        assert keys == ["fixture_api_board", "fixture_search_feed", "fixture_manual_pasted"]

    def test_load_empty_registry(self) -> None:
        """Verify an explicit empty registry parses cleanly."""
        path = FIXTURES_DIR / "empty_registry.json"
        envelope, issues = load_source_registry(path)
        assert envelope.schema_version == "1.0"
        assert len(envelope.sources) == 0

    def test_load_nonexistent_file_raises_filenotfound(self, tmp_path: Path) -> None:
        """Verify non-existent file path raises FileNotFoundError."""
        missing = tmp_path / "does_not_exist.json"
        with pytest.raises(FileNotFoundError, match="Source registry file not found"):
            load_source_registry(missing)

    def test_load_unsupported_schema_version(self) -> None:
        """Verify unsupported schema_version is rejected."""
        path = FIXTURES_DIR / "invalid_unsupported_schema.json"
        with pytest.raises(ValueError, match="Unsupported source registry schema_version"):
            load_source_registry(path)

    def test_load_duplicate_source_key_rejected(self) -> None:
        """Verify duplicate source_key entries are rejected."""
        path = FIXTURES_DIR / "invalid_duplicate_source_key.json"
        with pytest.raises(ValueError, match="Duplicate source_key 'duplicate_key'"):
            load_source_registry(path)

    def test_load_duplicate_json_key_rejected(self) -> None:
        """Verify duplicate keys within a JSON object are rejected."""
        path = FIXTURES_DIR / "invalid_duplicate_json_key.json"
        with pytest.raises(ValueError, match="Duplicate JSON key"):
            load_source_registry(path)

    def test_load_with_utf8_bom(self, tmp_path: Path) -> None:
        """Verify UTF-8 files containing BOM (\xef\xbb\xbf) load without error."""
        bom_file = tmp_path / "bom_registry.json"
        content = json.dumps({"schema_version": "1.0", "sources": []}).encode("utf-8")
        bom_file.write_bytes(b"\xef\xbb\xbf" + content)

        envelope, _ = load_source_registry(bom_file)
        assert envelope.schema_version == "1.0"
        assert len(envelope.sources) == 0

    def test_file_handle_released_immediately(self, tmp_path: Path) -> None:
        """Verify on native Windows that the file handle is released and file can be renamed."""
        reg_file = tmp_path / "temp_reg.json"
        reg_file.write_text(json.dumps({"schema_version": "1.0", "sources": []}), encoding="utf-8")

        load_source_registry(reg_file)

        # On Windows, if a file handle remains open, rename raises PermissionError
        renamed_file = tmp_path / "renamed_temp_reg.json"
        reg_file.rename(renamed_file)
        assert renamed_file.is_file()
        assert not reg_file.exists()

