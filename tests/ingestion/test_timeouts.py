"""Tests for monotonic deadline enforcement and timeout handling (INGEST-01-S04)."""

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
from job_automation.ingestion.ports import ClockProtocol, SleeperProtocol
from job_automation.ingestion.request_control import DomainRateLimiter
from job_automation.sources.models import EffectiveSource
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine


class MonotonicDeadlineClock(ClockProtocol):
    def __init__(self, start_mono: float = 1000.0) -> None:
        self._mono = start_mono
        self._utc = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)

    def now_utc(self) -> datetime:
        return self._utc

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._mono += seconds


class NullSleeper(SleeperProtocol):
    def sleep(self, seconds: float) -> None:
        pass


class InfinitePaginatedAdapter(Adapter):
    def __init__(self, clock: MonotonicDeadlineClock):
        self.clock = clock
        self.call_count = 0

    def fetch_page(self, config, continuation=None) -> AdapterPage:
        self.call_count += 1
        page_num = int(continuation.value) if continuation else 1

        # Advance clock on each page fetch so deadline expires after page 1
        self.clock.advance(60.0)

        raw = RawPosting(
            raw_payload_ref=f"raw://{page_num}",
            raw_content_hash="sha256:" + f"{page_num:02x}" * 32,
            source_key=SourceKey(provider=config.provider, board_id=config.board_id, source_posting_id=f"job_{page_num}"),
            fetch_time=datetime.now(timezone.utc),
            raw_payload="{}",
        )
        cont_next = Continuation(
            kind="page",
            value=str(page_num + 1),
            source_key=config.source_key,
            scope_id=f"{config.provider}_{config.board_id}",
            adapter_name="infinite",
        )
        return AdapterPage(
            items=[raw],
            issues=[],
            continuation_in=continuation,
            continuation_out=cont_next,
            exhausted=False,
        )

    def draft_posting(self, raw):
        from job_automation.contracts.adapter_results import DraftResult
        from job_automation.contracts.postings import SourceJobDraft
        draft = SourceJobDraft(
            raw_reference=raw.raw_payload_ref,
            source_key=raw.source_key,
            fetch_time=raw.fetch_time,
            original_fields={},
            source_mapped_fields={"title": "T", "source_url": "https://example.invalid"},
        )
        return DraftResult(raw_reference=raw.raw_payload_ref, draft=draft, issues=[])


def test_monotonic_deadline_halts_traversal_as_partial(tmp_path: Path):
    db_path = tmp_path / "data" / "sqlite" / "timeout.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    cfg = SourceConfig(
        source_key="timeout_src",
        provider="prov_time",
        board_id="board_time",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)

    # Deadline of 50 seconds; adapter advances 60 seconds on page 1
    opts = ControllerOptions(max_pages=100, source_deadline_seconds=50.0)
    clock = MonotonicDeadlineClock(100.0)
    sleeper = NullSleeper()
    adapter = InfinitePaginatedAdapter(clock)
    sink = DurableRawCaptureSink(raw_dir)
    rate_limiter = DomainRateLimiter()
    cache = PageCache(raw_dir, ttl_seconds=0)

    traverser = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=opts,
        clock=clock,
        sleeper=sleeper,
        rate_limiter=rate_limiter,
        cache=cache,
    )

    res = traverser.traverse()

    # Must halt after 1 page because deadline was exceeded
    assert adapter.call_count == 1
    assert res.page_count == 1
    # CRITICAL INVARIANT: Interrupted pagination must be PARTIAL, NEVER COMPLETE
    assert res.outcome == FetchOutcome.PARTIAL
    assert res.manifest.outcome == FetchOutcome.PARTIAL
    assert res.manifest.cursor_out is not None

