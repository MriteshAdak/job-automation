"""Tests for adapter boundary contracts and auxiliary models (SOURCE-02-S01)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey


def test_continuation_encode_decode_round_trip() -> None:
    c = Continuation(
        kind="cursor",
        value="page_cursor_token_42",
        source_key="arbeitnow_de",
        scope_id="scope-v1:abc123def456",
        adapter_name="arbeitnow_adapter",
        input_hash="sha256:" + "a" * 64,
        options_hash="sha256:" + "b" * 64,
    )
    token = c.encode()
    assert token.startswith("cont-v1:")
    decoded = Continuation.decode(token)
    assert decoded == c


def test_continuation_decode_invalid() -> None:
    with pytest.raises(ValueError, match="Unsupported continuation token prefix"):
        Continuation.decode("invalid_token")

    with pytest.raises(ValueError, match="Malformed continuation token"):
        Continuation.decode("cont-v1:not_valid_base64!!!")


def test_record_issue_validation() -> None:
    issue = RecordIssue(
        input_ref="memory://test.csv",
        input_hash="sha256:" + "0" * 64,
        record_index=2,
        line_start=3,
        line_end=5,
        code="invalid_source_url",
        severity="error",
        message="Invalid URL provided on row 2",
        category=ErrorCategory.VALIDATION,
    )
    assert issue.record_index == 2
    assert issue.severity == "error"

    # Invalid severity
    with pytest.raises(ValidationError):
        RecordIssue(
            input_ref="memory://test.csv",
            input_hash="sha256:" + "0" * 64,
            code="test",
            severity="critical",  # Only 'error' or 'warning'
            message="bad severity",
        )


def test_adapter_page_exhausted_with_continuation_out_rejected() -> None:
    cont = Continuation(
        kind="cursor",
        value="token",
        source_key="src",
        scope_id="scope-1",
        adapter_name="adapter",
    )
    with pytest.raises(ValidationError, match="Contradictory page state"):
        AdapterPage(
            items=[],
            exhausted=True,
            continuation_out=cont,
        )


def test_adapter_page_round_trip() -> None:
    now = datetime.now(timezone.utc)
    sk = SourceKey(provider="prov", board_id="b1", source_posting_id="101")
    raw = RawPosting(
        raw_payload_ref="ref/101.json",
        raw_content_hash="sha256:" + "0" * 64,
        source_key=sk,
        fetch_time=now,
        raw_payload='{"title": "Software Engineer"}',
    )
    issue = RecordIssue(
        input_ref="ref/101.json",
        input_hash="sha256:" + "0" * 64,
        record_index=1,
        code="missing_title",
        severity="warning",
        message="Title was missing from payload",
    )
    page = AdapterPage(
        items=[raw],
        issues=[issue],
        raw_response_refs=["ref/101.json"],
        exhausted=True,
    )
    assert page.record_count == 1
    assert page.issue_count == 1

    dumped = page.model_dump(mode="json")
    reloaded = AdapterPage.model_validate(dumped)
    assert reloaded == page


def test_draft_result_valid_with_warnings() -> None:
    now = datetime.now(timezone.utc)
    sk = SourceKey(provider="prov", board_id="b1", source_posting_id="101")
    draft = SourceJobDraft(
        raw_reference="ref/101.json",
        source_key=sk,
        fetch_time=now,
        original_fields={"title": "Dev"},
        source_mapped_fields={"title": "Dev"},
    )
    warning_issue = RecordIssue(
        input_ref="ref/101.json",
        input_hash="sha256:" + "0" * 64,
        code="field_warning",
        severity="warning",
        message="Non-blocking warning",
    )
    res = DraftResult(
        raw_reference="ref/101.json",
        draft=draft,
        issues=[warning_issue],
    )
    assert res.draft is not None
    assert len(res.issues) == 1


def test_draft_result_blocking_error_without_draft() -> None:
    error_issue = RecordIssue(
        input_ref="ref/101.json",
        input_hash="sha256:" + "0" * 64,
        code="missing_source_url",
        severity="error",
        message="Source URL is required",
    )
    res = DraftResult(
        raw_reference="ref/101.json",
        draft=None,
        issues=[error_issue],
    )
    assert res.draft is None
    assert len(res.issues) == 1


def test_draft_result_invariants_enforced() -> None:
    now = datetime.now(timezone.utc)
    sk = SourceKey(provider="prov", board_id="b1", source_posting_id="101")
    draft = SourceJobDraft(
        raw_reference="ref/101.json",
        source_key=sk,
        fetch_time=now,
        original_fields={"title": "Dev"},
        source_mapped_fields={"title": "Dev"},
    )
    error_issue = RecordIssue(
        input_ref="ref/101.json",
        input_hash="sha256:" + "0" * 64,
        code="blocking_error",
        severity="error",
        message="Blocking error",
    )

    # 1. Draft with blocking error -> invalid
    with pytest.raises(ValidationError, match="DraftResult cannot contain a draft when blocking error issues exist"):
        DraftResult(
            raw_reference="ref/101.json",
            draft=draft,
            issues=[error_issue],
        )

    # 2. No draft without blocking error -> invalid
    with pytest.raises(ValidationError, match="DraftResult with no blocking error issues must contain a draft"):
        DraftResult(
            raw_reference="ref/101.json",
            draft=None,
            issues=[],
        )

    # 3. Reference mismatch -> invalid
    with pytest.raises(ValidationError, match="raw_reference mismatch"):
        DraftResult(
            raw_reference="ref/different.json",
            draft=draft,
            issues=[],
        )

