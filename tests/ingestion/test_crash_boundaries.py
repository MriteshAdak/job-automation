"""Tests for crash boundary integrity and restart persistence (INGEST-01-S05)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.adapter_results import AdapterPage, Continuation
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.pagination import PaginationTraverser
from job_automation.ingestion.persistence import PagePersistenceManager
from job_automation.ingestion.ports import SystemClock, SystemSleeper
from job_automation.ingestion.request_control import DomainRateLimiter
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def test_crash_boundary_persistence(tmp_path: Path):
    db_path = tmp_path / "crash" / "data.db"
    raw_dir = tmp_path / "crash" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4()

    # Session 1: initialize and run 1 page then exit
    engine1 = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    engine1.migrate()
    engine1.runs.create_run(run_id=run_id)

    cfg = SourceConfig(
        source_key="crash_src",
        provider="crash_prov",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)
    sink1 = DurableRawCaptureSink(raw_dir)

    cont2 = Continuation(kind="page", value="2", source_key="crash_src", scope_id="crash_prov_default", adapter_name="fake")

    raw1 = RawPosting(
        raw_payload_ref="raw://1",
        raw_content_hash="sha256:" + "c" * 64,
        source_key=SourceKey(provider="crash_prov", board_id="default", source_posting_id="c_01"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"id": "c_01"}',
    )
    page1 = AdapterPage(items=[raw1], issues=[], continuation_in=None, continuation_out=cont2, exhausted=False)
    pages = {None: page1}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="crash_src")

    trav1 = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=engine1,
        sink=sink1,
        options=ControllerOptions(max_pages=1),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(raw_dir, ttl_seconds=0),
    )
    res1 = trav1.traverse()
    assert res1.outcome == FetchOutcome.PARTIAL

    # Close first engine (simulating process exit/crash)
    engine1.close()

    # Session 2: Fresh engine instance from disk
    engine2 = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    try:
        # Verify raw posting was preserved
        fetched_raw = engine2.raw_postings.get_raw_posting(raw1.source_key)
        assert fetched_raw is not None
        assert fetched_raw.source_key == raw1.source_key

        # Verify checkpoint is intact
        mgr2 = PagePersistenceManager(engine2)
        loaded_chk = mgr2.load_checkpoint(run_id, "crash_src", "crash_prov_default")
        assert loaded_chk is not None
        assert loaded_chk.pages_completed == 1
        assert loaded_chk.current_continuation == cont2

        # Verify manifest is PARTIAL, NEVER COMPLETE
        manifests = engine2.raw_postings.get_manifests_for_run(run_id)
        assert len(manifests) == 1
        assert manifests[0].outcome == FetchOutcome.PARTIAL
    finally:
        engine2.close()

