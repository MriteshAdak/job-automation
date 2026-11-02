"""Unit tests for native Windows path safety and volume inspection (OPS-01-S02)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.operations.paths import (
    check_destination_overlap,
    is_same_physical_device,
    normalize_manifest_path,
    resolve_manifest_path,
    validate_safe_path,
)


def test_validate_safe_path_confinement(tmp_path: Path) -> None:
    base = tmp_path / "base_dir"
    base.mkdir()
    child = base / "sub" / "file.txt"
    child.parent.mkdir()
    child.write_text("hello")

    # Valid inside base
    validated = validate_safe_path(child, base)
    assert validated == child.resolve()

    # Traversal escape
    with pytest.raises(ValueError, match="Path traversal or junction escape"):
        validate_safe_path(base / ".." / "outside.txt", base)


def test_manifest_path_normalization_and_resolution(tmp_path: Path) -> None:
    base = tmp_path / "data_root"
    base.mkdir()
    raw_file = base / "raw" / "source" / "doc.json"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("{}")

    norm = normalize_manifest_path(raw_file, base)
    assert norm == "raw/source/doc.json"

    resolved = resolve_manifest_path(norm, base)
    assert resolved == raw_file.resolve()

    # Reject absolute or traversal paths in manifest
    with pytest.raises(ValueError, match="root-relative"):
        resolve_manifest_path("/etc/passwd", base)

    with pytest.raises(ValueError, match="traversal"):
        resolve_manifest_path("raw/../../secret.txt", base)


def test_destination_overlap_protection(tmp_path: Path) -> None:
    src_root = tmp_path / "Job Automation Prüfung ä"
    src_root.mkdir()
    raw_dir = src_root / "raw"
    raw_dir.mkdir()
    backups_dir = src_root / "backups"
    backups_dir.mkdir()

    # Disallow backup destination overlapping with raw payload directory
    with pytest.raises(ValueError, match="overlaps with managed payload directory"):
        check_destination_overlap(src_root, raw_dir)

    with pytest.raises(ValueError, match="overlaps with managed payload directory"):
        check_destination_overlap(src_root, raw_dir / "nested")

    # Disallow exact source data root
    with pytest.raises(ValueError, match="cannot be identical to source data root"):
        check_destination_overlap(src_root, src_root)

    # Allowed: separate backups directory
    check_destination_overlap(src_root, backups_dir)
    check_destination_overlap(src_root, tmp_path / "external_backup")


def test_physical_device_detection(tmp_path: Path) -> None:
    p1 = tmp_path / "folder1"
    p2 = tmp_path / "folder2"
    p1.mkdir()
    p2.mkdir()

    is_same, reason = is_same_physical_device(p1, p2)
    assert is_same is True
    assert "same_drive_letter" in reason or "same_filesystem" in reason

