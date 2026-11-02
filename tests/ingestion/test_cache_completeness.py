"""Tests proving cache reuse produces PARTIAL C04 manifests (INGEST-01-S06)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.adapter_results import AdapterPage
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.pagination import PaginationTraverser
from job_automation.ingestion.ports import SystemClock, SystemSleeper
from job_automation.ingestion.request_control import DomainRateLimiter
from job_automation.sources.models import EffectiveSource
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def test_cached_traversal_produces_partial_manifest(tmp_path: Path):
    db_path = tmp_path / "data" / "sqlite" / "cache_comp.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id1 = uuid.uuid4()
    storage.runs.create_run(run_id=run_id1)

    cfg = SourceConfig(
        source_key="cache_complete_src",
        provider="prov_cc",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)
    sink = DurableRawCaptureSink(raw_dir)

    raw1 = RawPosting(
        raw_payload_ref="raw://1",
        raw_content_hash="sha256:" + "f" * 64,
        source_key=SourceKey(provider="prov_cc", board_id="default", source_posting_id="cc_01"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"id": "cc_01"}',
    )
    page1 = AdapterPage(items=[raw1], issues=[], continuation_in=None, continuation_out=None, exhausted=True)
    pages = {None: page1}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="cache_complete_src")

    # Run 1: with cache enabled (TTL=3600)
    # This run fetches from network adapter, caches it, and produces COMPLETE
    cache = PageCache(raw_dir, ttl_seconds=3600)
    trav1 = PaginationTraverser(
        run_id=run_id1,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=10, cache_mode="ttl", cache_ttl_seconds=3600),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=cache,
    )
    res1 = trav1.traverse()
    assert res1.outcome == FetchOutcome.COMPLETE
    assert res1.requests_made == 1

    # Run 2: same source in a new run UUID, hits cache!
    run_id2 = uuid.uuid4()
    storage.runs.create_run(run_id=run_id2)

    # Empty adapter pages to prove adapter is NEVER called on cache hit!
    empty_adapter = ScriptedPaginatedFakeAdapter(pages={}, expected_source_key="cache_complete_src")
    trav2 = PaginationTraverser(
        run_id=run_id2,
        effective_source=eff,
        adapter=empty_adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=10, cache_mode="ttl", cache_ttl_seconds=3600),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=cache,
    )
    res2 = trav2.traverse()

    # CRITICAL INVARIANTS:
    # 1. Zero network requests made
    assert res2.requests_made == 0
    assert res2.from_cache_count == 1
    # 2. Reusing cached pages cannot authorize complete inventory: MUST BE PARTIAL
    assert res2.outcome == FetchOutcome.PARTIAL
    assert res2.manifest.outcome == FetchOutcome.PARTIAL
    assert res2.manifest.error is not None
    assert "cache_reuse" in str(res2.manifest.error.details)

