"""Tests for quarantine handoffs and independent record failure isolation (INGEST-02-S07)."""

from __future__ import annotations

import pytest

from job_automation.contracts.adapter_results import RecordIssue
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.errors import ErrorCategory, ValidationIssue
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.normalization import (
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
    QuarantineHandoff,
    build_quarantine_handoff,
)
from tests.fakes.normalization_inputs import create_sample_draft


def test_mixed_batch_failure_isolation() -> None:
    """A malformed record in a batch is quarantined while valid neighbors succeed."""
    reader = InMemoryRawProvenanceReader()

    # Record 1: Valid office posting
    draft_1 = create_sample_draft(
        raw_reference="memory://batch_job_1",
        raw_bytes=b"job 1 raw payload",
        source_key=SourceKey(provider="manual", board_id="b1", source_posting_id="rec-001"),
        title="Sachbearbeiter (m/w/d)",
        reader=reader,
    )

    # Record 2: Malformed (blank title and script-only description)
    draft_2 = create_sample_draft(
        raw_reference="memory://batch_job_2",
        raw_bytes=b"job 2 raw payload",
        source_key=SourceKey(provider="manual", board_id="b1", source_posting_id="rec-002"),
        title="",
        description="<script>evil()</script>",
        reader=reader,
    )

    # Record 3: Valid posting with unknown remote
    draft_3 = create_sample_draft(
        raw_reference="memory://batch_job_3",
        raw_bytes=b"job 3 raw payload",
        source_key=SourceKey(provider="manual", board_id="b1", source_posting_id="rec-003"),
        title="Software Architect",
        workplace_type_raw=True,  # remote without restrictions
        reader=reader,
    )

    normalizer = DefaultNormalizer(raw_reader=reader)

    results = [
        normalizer.normalize_with_quarantine(d, input_ref="batch.csv", record_index=idx)
        for idx, d in enumerate([draft_1, draft_2, draft_3])
    ]

    # Verify counts: 2 successful C06 postings, 1 quarantined record
    successes = [r for r in results if r.is_success]
    quarantined = [r for r in results if not r.is_success]

    assert len(successes) == 2
    assert len(quarantined) == 1

    # Record 1 is valid C06
    assert isinstance(results[0].posting, NormalizedPosting)
    assert results[0].posting.title == "Sachbearbeiter (m/w/d)"
    assert results[0].quarantine is None

    # Record 2 is quarantined with multiple issues retained
    q_rec = results[1].quarantine
    assert q_rec is not None
    assert isinstance(q_rec, QuarantineHandoff)
    assert q_rec.draft_reference == "memory://batch_job_2"
    assert q_rec.input_ref == "batch.csv"
    assert q_rec.record_index == 1
    issue_codes = {iss.code for iss in q_rec.issues}
    assert "empty_after_cleaning" in issue_codes

    # Record 3 is valid C06 with remote workplace and empty restrictions
    assert isinstance(results[2].posting, NormalizedPosting)
    assert results[2].posting.workplace_type == WorkplaceType.REMOTE
    assert results[2].posting.remote_eligibility_restrictions == []
    assert results[2].quarantine is None


def test_build_quarantine_handoff_from_record_issues() -> None:
    """build_quarantine_handoff converts upstream RecordIssues accurately."""
    rec_issue = RecordIssue(
        input_ref="raw_doc.html",
        input_hash="sha256:" + "a" * 64,
        record_index=1,
        field_path="title",
        code="missing_title",
        severity="error",
        message="Job title missing from document",
        category=ErrorCategory.VALIDATION,
    )

    q = build_quarantine_handoff(
        draft=None,
        issues=[rec_issue],
        input_ref="raw_doc.html",
        record_index=1,
    )

    assert q.input_ref == "raw_doc.html"
    assert q.record_index == 1
    assert len(q.issues) == 1
    assert q.issues[0].code == "missing_title"
    assert q.issues[0].severity == "error"
