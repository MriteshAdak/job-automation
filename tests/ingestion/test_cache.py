"""Tests for PageCache storage, hit/miss, and TTL expiry (INGEST-01-S06)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from job_automation.contracts.adapter_results import AdapterPage, DraftResult
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink


def _make_dummy_page_and_draft(sink: DurableRawCaptureSink) -> tuple[AdapterPage, list[DraftResult]]:
    content = b'{"job": "Cache Test"}'
    ref, c_hash = sink.capture(content, identifier_hint="cache_test")

    source_key = SourceKey(provider="c_prov", board_id="c_board", source_posting_id="c_01")
    raw = RawPosting(
        raw_payload_ref=ref,
        raw_content_hash=c_hash,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"job": "Cache Test"}',
    )
    draft = SourceJobDraft(
        raw_reference=ref,
        source_key=source_key,
        fetch_time=raw.fetch_time,
        original_fields={},
        source_mapped_fields={"title": "Cache Title", "source_url": "https://example.invalid"},
    )
    draft_res = DraftResult(raw_reference=ref, draft=draft, issues=[])
    page = AdapterPage(
        items=[raw],
        issues=[],
        raw_response_refs=[ref],
        exhausted=True,
    )
    return page, [draft_res]


def test_cache_put_and_get_hit(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    cache = PageCache(tmp_path, ttl_seconds=300)
    now = datetime.now(timezone.utc)

    page, drafts = _make_dummy_page_and_draft(sink)
    key = cache.compute_cache_key("src1", "scope1", "adapter1", "cont1")

    refs = [page.items[0].raw_payload_ref]
    hashes = [page.items[0].raw_content_hash]

    cache.put(
        cache_key=key,
        source_key="src1",
        scope_id="scope1",
        adapter_name="adapter1",
        continuation_token="cont1",
        raw_response_refs=refs,
        raw_response_hashes=hashes,
        page=page,
        draft_results=drafts,
        now_utc=now,
    )

    # Cache hit within TTL
    hit = cache.get(key, now + timedelta(seconds=60), sink)
    assert hit is not None
    cached_page, cached_drafts = hit
    assert len(cached_page.items) == 1
    assert cached_page.items[0].source_key.source_posting_id == "c_01"
    assert len(cached_drafts) == 1


def test_cache_miss_when_expired(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    cache = PageCache(tmp_path, ttl_seconds=60)
    now = datetime.now(timezone.utc)

    page, drafts = _make_dummy_page_and_draft(sink)
    key = cache.compute_cache_key("src2", "scope2", "adapter2", None)

    cache.put(
        cache_key=key,
        source_key="src2",
        scope_id="scope2",
        adapter_name="adapter2",
        continuation_token=None,
        raw_response_refs=[page.items[0].raw_payload_ref],
        raw_response_hashes=[page.items[0].raw_content_hash],
        page=page,
        draft_results=drafts,
        now_utc=now,
    )

    # After 61 seconds, TTL has expired -> miss
    hit = cache.get(key, now + timedelta(seconds=61), sink)
    assert hit is None


def test_cache_disabled_is_noop(tmp_path: Path):
    sink = DurableRawCaptureSink(tmp_path)
    cache = PageCache(tmp_path, ttl_seconds=0)
    assert not cache.is_enabled

    page, drafts = _make_dummy_page_and_draft(sink)
    key = cache.compute_cache_key("src3", "scope3", "adapter3", None)

    cache.put(
        cache_key=key,
        source_key="src3",
        scope_id="scope3",
        adapter_name="adapter3",
        continuation_token=None,
        raw_response_refs=[page.items[0].raw_payload_ref],
        raw_response_hashes=[page.items[0].raw_content_hash],
        page=page,
        draft_results=drafts,
        now_utc=datetime.now(timezone.utc),
    )

    hit = cache.get(key, datetime.now(timezone.utc), sink)
    assert hit is None

