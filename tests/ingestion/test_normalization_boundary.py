"""Tests for Normalizer protocol boundary and result invariants (INGEST-02-S01)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from job_automation.contracts.interfaces import Normalizer
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization import (
    CaptureSinkProvenanceReader,
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
    NormalizationOptions,
    QuarantineHandoff,
)
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from tests.fakes.normalization_inputs import FIXED_FETCH_TIME, create_sample_draft


def test_normalizer_protocol_conformance() -> None:
    """DefaultNormalizer satisfies the boundary Normalizer Protocol."""
    normalizer = DefaultNormalizer()
    assert isinstance(normalizer, Normalizer)


def test_normalizer_successful_normalization() -> None:
    """Supported valid draft produces contract-valid C06 NormalizedPosting."""
    reader = InMemoryRawProvenanceReader()
    draft = create_sample_draft(reader=reader)
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert isinstance(posting, NormalizedPosting)
    assert not any(iss.severity == "error" for iss in issues)
    assert posting.title == "Sachbearbeiter (m/w/d)"
    assert posting.company_name_hint == "Beispiel GmbH"
    assert posting.source_key == draft.source_key
    assert posting.raw_reference == draft.raw_reference
    assert posting.raw_content_hash.startswith("sha256:")
    assert posting.observed_at == FIXED_FETCH_TIME


def test_normalizer_never_returns_none_empty_issues() -> None:
    """Normalizer never returns (None, []) when normalization fails."""
    normalizer = DefaultNormalizer()
    # Missing raw reference resolution
    draft = create_sample_draft(raw_reference="nonexistent_ref")
    posting, issues = normalizer.normalize(draft)

    assert posting is None
    assert len(issues) > 0
    assert any(iss.severity == "error" for iss in issues)
    assert any(iss.code == "raw_reference_unresolved" for iss in issues)


def test_raw_content_hash_integrity_mismatch() -> None:
    """Corrupt or altered raw bytes fail integrity check with raw_hash_mismatch."""
    reader = InMemoryRawProvenanceReader()
    ref = "memory://corrupt_job"
    real_bytes = b"real content"
    wrong_hash = "sha256:" + "0" * 64
    reader.register(ref, real_bytes, content_hash=wrong_hash)

    draft = create_sample_draft(raw_reference=ref)
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    assert posting is None
    assert any(iss.code == "raw_hash_mismatch" for iss in issues)


def test_unsupported_mapping_version_rejected() -> None:
    """Draft with an unknown mapping version produces unsupported_mapping_version issue."""
    reader = InMemoryRawProvenanceReader()
    draft = create_sample_draft(mapping_version="99.9", reader=reader)
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting, issues = normalizer.normalize(draft)

    assert posting is None
    assert any(iss.code == "unsupported_mapping_version" for iss in issues)


def test_quarantine_handoff_produced_on_error() -> None:
    """normalize_with_quarantine produces inspectable QuarantineHandoff on error."""
    reader = InMemoryRawProvenanceReader()
    # Blank title causes fatal error
    draft = create_sample_draft(title="", reader=reader)
    normalizer = DefaultNormalizer(raw_reader=reader)

    res = normalizer.normalize_with_quarantine(draft, input_ref="file_1.csv", record_index=3)

    assert res.posting is None
    assert not res.is_success
    assert res.quarantine is not None
    assert isinstance(res.quarantine, QuarantineHandoff)
    assert res.quarantine.draft_reference == draft.raw_reference
    assert res.quarantine.input_ref == "file_1.csv"
    assert res.quarantine.record_index == 3
    assert any(iss.code == "empty_after_cleaning" for iss in res.quarantine.issues)


def test_replay_idempotency() -> None:
    """Re-normalizing the same draft and raw bytes produces identical outputs and issues."""
    reader = InMemoryRawProvenanceReader()
    draft = create_sample_draft(reader=reader)
    normalizer = DefaultNormalizer(raw_reader=reader)

    posting1, issues1 = normalizer.normalize(draft)
    posting2, issues2 = normalizer.normalize(draft)

    assert posting1 == posting2
    assert [i.model_dump() for i in issues1] == [i.model_dump() for i in issues2]


def test_capture_sink_adaptation() -> None:
    """CaptureSinkProvenanceReader correctly adapts RawCaptureSink."""
    sink = InMemoryRawCaptureSink()
    ref, h = sink.capture(b"bytes in sink", identifier_hint="test")
    normalizer = DefaultNormalizer(raw_reader=sink)

    draft = create_sample_draft(raw_reference=ref)
    posting, issues = normalizer.normalize(draft)

    assert posting is not None
    assert posting.raw_content_hash == h

