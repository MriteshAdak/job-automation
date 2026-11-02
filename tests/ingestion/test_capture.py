"""Tests for DurableRawCaptureSink (INGEST-01-S02)."""

from pathlib import Path
import pytest

from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.sources.adapters.raw import compute_content_hash, verify_content_hash


def test_durable_raw_capture_exact_bytes(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)

    # 1. UTF-8 with BOM and CRLF
    bom_content = b"\xef\xbb\xbfLine 1\r\nLine 2\r\nSpecial: \xc3\xa4\xc3\xb6\xc3\xbc"
    ref, c_hash = sink.capture(bom_content, identifier_hint="bom_test")

    assert c_hash == compute_content_hash(bom_content)
    assert Path(ref).is_file()

    read_back = sink.get(ref)
    assert read_back == bom_content
    assert verify_content_hash(read_back, c_hash)


def test_durable_raw_capture_idempotent_reuse(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    sample_bytes = b'{"status": "ok", "items": [1, 2, 3]}'

    ref1, hash1 = sink.capture(sample_bytes, identifier_hint="feed_page_1")
    ref2, hash2 = sink.capture(sample_bytes, identifier_hint="feed_page_1")

    assert ref1 == ref2
    assert hash1 == hash2
    assert sink.get(ref1) == sample_bytes


def test_durable_raw_capture_hostile_identifier_hints(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    content = b"hostile hint test"

    # Hostile characters that could cause directory traversal or invalid Windows filenames
    hostile_hint = r"..\..\Windows\System32\cmd.exe:<>|?*"
    ref, c_hash = sink.capture(content, identifier_hint=hostile_hint)

    # Target file must reside strictly inside tmp_path / "captures"
    ref_path = Path(ref).resolve()
    assert ref_path.is_relative_to((tmp_path / "captures").resolve())
    assert ref_path.is_file()
    assert sink.get(ref) == content


def test_durable_raw_capture_path_traversal_rejection(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)

    # Attempt to read outside raw_dir
    outside_file = tmp_path.parent / "secret.txt"
    outside_file.write_bytes(b"sensitive")

    with pytest.raises(ValueError, match="Path traversal or out-of-root"):
        sink.get(str(outside_file.resolve()))

    with pytest.raises(ValueError, match="Path traversal or out-of-root"):
        sink.get(f"file://{outside_file.as_posix()}")


def test_durable_raw_capture_nonexistent_returns_none(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    non_existent = tmp_path / "captures" / "does_not_exist.dat"
    assert sink.get(str(non_existent)) is None

