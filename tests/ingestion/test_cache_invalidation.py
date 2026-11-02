"""Tests for cache invalidation on tampered or missing evidence (INGEST-01-S06)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_automation.contracts.adapter_results import AdapterPage, DraftResult
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink


def _make_dummy_page_and_draft(sink: DurableRawCaptureSink) -> tuple[AdapterPage, list[DraftResult]]:
    content = b'{"job": "Integrity Test"}'
    ref, c_hash = sink.capture(content, identifier_hint="integrity")

    source_key = SourceKey(provider="i_prov", board_id="i_board", source_posting_id="i_01")
    raw = RawPosting(
        raw_payload_ref=ref,
        raw_content_hash=c_hash,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"job": "Integrity Test"}',
    )
    draft = SourceJobDraft(
        raw_reference=ref,
        source_key=source_key,
        fetch_time=raw.fetch_time,
        original_fields={},
        source_mapped_fields={"title": "T", "source_url": "https://example.invalid"},
    )
    draft_res = DraftResult(raw_reference=ref, draft=draft, issues=[])
    page = AdapterPage(items=[raw], issues=[], raw_response_refs=[ref], exhausted=True)
    return page, [draft_res]


def test_cache_invalidated_when_raw_file_deleted(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    cache = PageCache(tmp_path, ttl_seconds=300)
    now = datetime.now(timezone.utc)

    page, drafts = _make_dummy_page_and_draft(sink)
    key = cache.compute_cache_key("src_del", "scope_del", "adapter", None)

    cache.put(
        cache_key=key,
        source_key="src_del",
        scope_id="scope_del",
        adapter_name="adapter",
        continuation_token=None,
        raw_response_refs=[page.items[0].raw_payload_ref],
        raw_response_hashes=[page.items[0].raw_content_hash],
        page=page,
        draft_results=drafts,
        now_utc=now,
    )

    # Delete the underlying raw file
    raw_path = Path(page.items[0].raw_payload_ref)
    assert raw_path.is_file()
    raw_path.unlink()

    # Cache should detect missing payload and return None
    hit = cache.get(key, now + timedelta(seconds=10), sink)
    assert hit is None


def test_cache_invalidated_when_raw_file_tampered(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    cache = PageCache(tmp_path, ttl_seconds=300)
    now = datetime.now(timezone.utc)

    page, drafts = _make_dummy_page_and_draft(sink)
    key = cache.compute_cache_key("src_tamp", "scope_tamp", "adapter", None)

    cache.put(
        cache_key=key,
        source_key="src_tamp",
        scope_id="scope_tamp",
        adapter_name="adapter",
        continuation_token=None,
        raw_response_refs=[page.items[0].raw_payload_ref],
        raw_response_hashes=[page.items[0].raw_content_hash],
        page=page,
        draft_results=drafts,
        now_utc=now,
    )

    # Overwrite the file with tampered bytes
    raw_path = Path(page.items[0].raw_payload_ref)
    raw_path.write_bytes(b'{"job": "TAMPERED"}')

    # Hash verification must fail -> returns None
    hit = cache.get(key, now + timedelta(seconds=10), sink)
    assert hit is None

