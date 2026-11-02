"""Tests for ImportReport diagnostics and safe error isolation (SOURCE-02-S06)."""

from __future__ import annotations

import pytest

from job_automation.contracts.adapter_results import AdapterPage, RecordIssue
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.sources.adapters.import_report import build_import_report


def test_build_import_report_accepted_with_warnings() -> None:
    raw = RawPosting(
        raw_payload_ref="ref/001",
        raw_content_hash="sha256:" + "0" * 64,
        source_key=SourceKey(provider="m", board_id="b", source_posting_id="1"),
        fetch_time="2026-10-28T09:00:00Z",
        raw_payload="{}",
    )
    warning_issue = RecordIssue(
        input_ref="file://jobs.csv",
        input_hash="sha256:" + "0" * 64,
        record_index=1,
        code="missing_title",
        severity="warning",
        message="Title was missing",
    )
    page = AdapterPage(
        items=[raw],
        issues=[warning_issue],
        exhausted=True,
    )

    report = build_import_report([page])
    assert report.status == "accepted"
    assert report.records_encountered == 1
    assert report.records_accepted == 1
    assert report.records_rejected == 0
    assert report.records_with_warnings == 1
    assert report.total_issues == 1
    assert report.scan_complete


def test_build_import_report_mixed_partial() -> None:
    raw = RawPosting(
        raw_payload_ref="ref/001",
        raw_content_hash="sha256:" + "0" * 64,
        source_key=SourceKey(provider="m", board_id="b", source_posting_id="1"),
        fetch_time="2026-10-28T09:00:00Z",
        raw_payload="{}",
    )
    # 2 error issues on record 2
    err_issue_1 = RecordIssue(
        input_ref="file://jobs.csv",
        input_hash="sha256:" + "0" * 64,
        record_index=2,
        code="missing_source_url",
        severity="error",
        message="Missing URL",
    )
    err_issue_2 = RecordIssue(
        input_ref="file://jobs.csv",
        input_hash="sha256:" + "0" * 64,
        record_index=2,
        code="missing_posting_text",
        severity="error",
        message="Missing Text",
    )
    page = AdapterPage(
        items=[raw],
        issues=[err_issue_1, err_issue_2],
        exhausted=True,
    )

    report = build_import_report([page])
    assert report.status == "partial"
    assert report.records_encountered == 2
    assert report.records_accepted == 1
    # Multiple issues on record 2 still count as 1 rejected record!
    assert report.records_rejected == 1
    assert report.total_issues == 2
    assert len(report.guidance) == 1
    assert "Record 2: rejected due to missing_source_url, missing_posting_text" in report.guidance[0]


def test_build_import_report_all_failed() -> None:
    err_issue = RecordIssue(
        input_ref="file://jobs.csv",
        input_hash="sha256:" + "0" * 64,
        record_index=1,
        code="invalid_source_url",
        severity="error",
        message="Invalid URL",
    )
    page = AdapterPage(
        items=[],
        issues=[err_issue],
        exhausted=True,
    )

    report = build_import_report([page])
    assert report.status == "failed"
    assert report.records_encountered == 1
    assert report.records_accepted == 0
    assert report.records_rejected == 1


def test_build_import_report_empty_valid_input() -> None:
    page = AdapterPage(
        items=[],
        issues=[],
        exhausted=True,
    )
    report = build_import_report([page])
    assert report.status == "accepted"
    assert report.records_encountered == 0
    assert report.records_accepted == 0
    assert report.records_rejected == 0
    assert report.total_issues == 0


def test_build_import_report_fatal_page_error() -> None:
    err = ClassifiedError.from_category(
        category=ErrorCategory.VALIDATION,
        message="CSV contains duplicate header",
        details={"code": "duplicate_csv_header"},
    )
    page = AdapterPage(
        items=[],
        issues=[],
        exhausted=True,
        page_error=err,
    )
    report = build_import_report([page])
    assert report.status == "failed"
    assert not report.scan_complete
    assert report.page_error is not None
    assert report.page_error.details is not None
    assert report.page_error.details.get("code") == "duplicate_csv_header"
