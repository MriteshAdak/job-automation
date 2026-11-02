"""Tests for pagination traversal, cycle detection, and honest completeness (INGEST-01-S05)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import AdapterPage, Continuation
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.interfaces import Adapter
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


@pytest.fixture
def test_setup(tmp_path: Path):
    db_path = tmp_path / "data" / "sqlite" / "paged.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    cfg = SourceConfig(
        source_key="paged_src",
        provider="prov_paged",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)
    sink = DurableRawCaptureSink(raw_dir)

    return storage, eff, sink, run_id


def _make_posting(provider: str, board_id: str, posting_id: str, num: int) -> RawPosting:
    return RawPosting(
        raw_payload_ref=f"raw://{posting_id}",
        raw_content_hash="sha256:" + f"{num:02x}" * 32,
        source_key=SourceKey(provider=provider, board_id=board_id, source_posting_id=posting_id),
        fetch_time=datetime.now(timezone.utc),
        raw_payload=f'{{"id": "{posting_id}"}}',
    )


def test_three_page_complete_traversal(test_setup):
    storage, eff, sink, run_id = test_setup
    p = eff.config.provider
    b = eff.config.board_id

    cont2 = Continuation(kind="page", value="2", source_key="paged_src", scope_id=f"{p}_{b}", adapter_name="fake")
    cont3 = Continuation(kind="page", value="3", source_key="paged_src", scope_id=f"{p}_{b}", adapter_name="fake")

    # Page 1: 2 records -> cont2
    page1 = AdapterPage(
        items=[_make_posting(p, b, "job_1", 1), _make_posting(p, b, "job_2", 2)],
        issues=[],
        continuation_in=None,
        continuation_out=cont2,
        exhausted=False,
    )
    # Page 2: 0 records -> cont3 (empty intermediate page)
    page2 = AdapterPage(
        items=[],
        issues=[],
        continuation_in=cont2,
        continuation_out=cont3,
        exhausted=False,
    )
    # Page 3: 1 record -> exhausted
    page3 = AdapterPage(
        items=[_make_posting(p, b, "job_3", 3)],
        issues=[],
        continuation_in=cont3,
        continuation_out=None,
        exhausted=True,
    )

    pages = {None: page1, "2": page2, "3": page3}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="paged_src")

    traverser = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=10),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(storage.raw_dir, ttl_seconds=0),
    )

    res = traverser.traverse()

    assert res.page_count == 3
    assert res.observed_identities_count == 3
    assert res.raw_records_count == 3
    assert res.outcome == FetchOutcome.COMPLETE
    assert res.manifest.outcome == FetchOutcome.COMPLETE
    assert res.manifest.cursor_out is None
    assert res.manifest.error is None


def test_pagination_stopped_at_page_cap_is_partial(test_setup):
    storage, eff, sink, run_id = test_setup
    p = eff.config.provider
    b = eff.config.board_id

    cont2 = Continuation(kind="page", value="2", source_key="paged_src", scope_id=f"{p}_{b}", adapter_name="fake")
    cont3 = Continuation(kind="page", value="3", source_key="paged_src", scope_id=f"{p}_{b}", adapter_name="fake")

    page1 = AdapterPage(items=[_make_posting(p, b, "j1", 1)], issues=[], continuation_in=None, continuation_out=cont2, exhausted=False)
    page2 = AdapterPage(items=[_make_posting(p, b, "j2", 2)], issues=[], continuation_in=cont2, continuation_out=cont3, exhausted=False)

    pages = {None: page1, "2": page2}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="paged_src")

    # Set cap at 2 pages
    traverser = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=2),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(storage.raw_dir, ttl_seconds=0),
    )

    res = traverser.traverse()

    assert res.page_count == 2
    # CRITICAL INVARIANT: Reaching page cap must be PARTIAL, NEVER COMPLETE
    assert res.outcome == FetchOutcome.PARTIAL
    assert res.manifest.outcome == FetchOutcome.PARTIAL
    assert res.manifest.cursor_out is not None


def test_pagination_cycle_detection(test_setup):
    storage, eff, sink, run_id = test_setup
    p = eff.config.provider
    b = eff.config.board_id

    cont2 = Continuation(kind="page", value="2", source_key="paged_src", scope_id=f"{p}_{b}", adapter_name="fake")
    # Cycle: page 2 returns continuation back to initial / None or already visited cont2!
    page1 = AdapterPage(items=[_make_posting(p, b, "j1", 1)], issues=[], continuation_in=None, continuation_out=cont2, exhausted=False)
    page2 = AdapterPage(items=[_make_posting(p, b, "j2", 2)], issues=[], continuation_in=cont2, continuation_out=cont2, exhausted=False)

    pages = {None: page1, "2": page2}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="paged_src")

    traverser = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=10),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(storage.raw_dir, ttl_seconds=0),
    )

    res = traverser.traverse()

    # Cycle detected: stops
    assert res.outcome == FetchOutcome.PARTIAL
    assert res.error is not None
    assert "cycle" in res.error.message.lower()

