"""Tests for checked single-page adapter execution and issue isolation (INGEST-01-S03)."""

from datetime import datetime, timezone

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.execution import PageExecutor
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveSource,
)
from job_automation.sources.validation import validate_source_config


def _make_source(provider: str = "testprov", board: str = "testboard") -> EffectiveSource:
    cfg = SourceConfig(
        source_key="test_source",
        provider=provider,
        board_id=board,
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid/feed",
        access_rules='{"status": "permitted"}',
        attribution_rules='{"status": "none_required"}',
    )
    return validate_source_config(cfg)


class FakeMockAdapter(Adapter):
    def __init__(self, page: AdapterPage, failing_posting_id: str | None = None):
        self.page = page
        self.failing_posting_id = failing_posting_id

    def fetch_page(self, config, continuation=None) -> AdapterPage:
        return self.page

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        if self.failing_posting_id and raw.source_key.source_posting_id == self.failing_posting_id:
            raise RuntimeError("Simulated mapping crash for this record")

        draft = SourceJobDraft(
            raw_reference=raw.raw_payload_ref,
            source_key=raw.source_key,
            fetch_time=raw.fetch_time,
            original_fields={},
            source_mapped_fields={"title": "Mapped Title", "source_url": "https://example.invalid"},
        )
        return DraftResult(raw_reference=raw.raw_payload_ref, draft=draft, issues=[])


def test_page_executor_success():
    eff = _make_source("provA", "boardA")
    raw1 = RawPosting(
        raw_payload_ref="raw://1",
        raw_content_hash="sha256:" + "1" * 64,
        source_key=SourceKey(provider="provA", board_id="boardA", source_posting_id="p1"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    raw2 = RawPosting(
        raw_payload_ref="raw://2",
        raw_content_hash="sha256:" + "2" * 64,
        source_key=SourceKey(provider="provA", board_id="boardA", source_posting_id="p2"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    page = AdapterPage(
        items=[raw1, raw2],
        issues=[],
        raw_response_refs=["raw://resp"],
        exhausted=True,
    )
    adapter = FakeMockAdapter(page)
    executor = PageExecutor(eff, adapter)
    res = executor.execute_page()

    assert len(res.raw_records) == 2
    assert res.observed_posting_ids == ["p1", "p2"]
    assert len(res.draft_results) == 2
    assert all(d.draft is not None for d in res.draft_results)
    assert len(res.all_issues) == 0


def test_page_executor_isolates_foreign_source_key():
    eff = _make_source("provA", "boardA")
    # Record 1 matches source
    raw1 = RawPosting(
        raw_payload_ref="raw://1",
        raw_content_hash="sha256:" + "1" * 64,
        source_key=SourceKey(provider="provA", board_id="boardA", source_posting_id="valid_1"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    # Record 2 has mismatched provider / board
    raw2 = RawPosting(
        raw_payload_ref="raw://2",
        raw_content_hash="sha256:" + "2" * 64,
        source_key=SourceKey(provider="foreign_prov", board_id="foreign_board", source_posting_id="foreign_2"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    page = AdapterPage(items=[raw1, raw2], issues=[], exhausted=True)
    adapter = FakeMockAdapter(page)
    executor = PageExecutor(eff, adapter)
    res = executor.execute_page()

    # Valid record preserved
    assert len(res.raw_records) == 1
    assert res.observed_posting_ids == ["valid_1"]
    assert len(res.draft_results) == 1

    # Foreign record rejected with issue
    assert any(i.code == "foreign_source_key_mismatch" for i in res.all_issues)


def test_page_executor_isolates_draft_mapping_exception():
    eff = _make_source("provA", "boardA")
    raw1 = RawPosting(
        raw_payload_ref="raw://1",
        raw_content_hash="sha256:" + "1" * 64,
        source_key=SourceKey(provider="provA", board_id="boardA", source_posting_id="good_1"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    raw2 = RawPosting(
        raw_payload_ref="raw://2",
        raw_content_hash="sha256:" + "2" * 64,
        source_key=SourceKey(provider="provA", board_id="boardA", source_posting_id="bad_2"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload="{}",
    )
    page = AdapterPage(items=[raw1, raw2], issues=[], exhausted=True)
    # bad_2 will raise during draft_posting
    adapter = FakeMockAdapter(page, failing_posting_id="bad_2")
    executor = PageExecutor(eff, adapter)
    res = executor.execute_page()

    # Both raw records kept as evidence
    assert len(res.raw_records) == 2
    assert res.observed_posting_ids == ["good_1", "bad_2"]

    # One draft succeeded, one has blocking issue
    assert res.draft_results[0].draft is not None
    assert res.draft_results[1].draft is None
    assert any(i.code == "draft_mapping_exception" for i in res.draft_results[1].issues)
