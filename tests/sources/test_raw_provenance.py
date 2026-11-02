"""Tests for raw capture, byte hashing, and immutable provenance (SOURCE-02-S03)."""

from __future__ import annotations

import hashlib
import pytest

from job_automation.sources.adapters.raw import (
    InMemoryRawCaptureSink,
    compute_content_hash,
    verify_content_hash,
)


def test_compute_content_hash() -> None:
    data = b"Hello, Job Automation!\n"
    expected = f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert compute_content_hash(data) == expected
    assert verify_content_hash(data, expected)
    assert not verify_content_hash(data, "sha256:" + "0" * 64)


def test_in_memory_raw_capture_sink() -> None:
    sink = InMemoryRawCaptureSink()
    content = "Senior Entwickler (m/w/d) Prüfung ä ö ü ß".encode("utf-8")

    ref, h = sink.capture(content, identifier_hint="test_german")
    assert ref.startswith("memory://test_german_")
    assert h == compute_content_hash(content)

    retrieved = sink.get(ref)
    assert retrieved == content
    assert sink.get("memory://non_existent") is None

