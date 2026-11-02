"""Tests for checkpoint-based pagination resumption (INGEST-01-S05)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import AdapterPage, Continuation
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


def _make_posting(provider: str, board_id: str, posting_id: str, num: int) -> RawPosting:
    return RawPosting(
        raw_payload_ref=f"raw://{posting_id}",
        raw_content_hash="sha256:" + f"{num:02x}" * 32,
        source_key=SourceKey(provider=provider, board_id=board_id, source_posting_id=posting_id),
        fetch_time=datetime.now(timezone.utc),
        raw_payload=f'{{"id": "{posting_id}"}}',
    )


def test_resume_from_checkpoint(tmp_path: Path):
    db_path = tmp_path / "data" / "sqlite" / "resume.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    cfg = SourceConfig(
        source_key="resumable_src",
        provider="prov_res",
        board_id="board_res",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)
    sink = DurableRawCaptureSink(raw_dir)

    p = eff.config.provider
    b = eff.config.board_id

    cont2 = Continuation(kind="page", value="2", source_key="resumable_src", scope_id=f"{p}_{b}", adapter_name="fake")

    page1 = AdapterPage(
        items=[_make_posting(p, b, "job_1", 1)],
        issues=[],
        continuation_in=None,
        continuation_out=cont2,
        exhausted=False,
    )
    page2 = AdapterPage(
        items=[_make_posting(p, b, "job_2", 2)],
        issues=[],
        continuation_in=cont2,
        continuation_out=None,
        exhausted=True,
    )

    pages = {None: page1, "2": page2}
    adapter = ScriptedPaginatedFakeAdapter(pages=pages, expected_source_key="resumable_src")

    # Run 1: max_pages=1 to stop after page 1
    trav1 = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=1),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(raw_dir, ttl_seconds=0),
    )
    res1 = trav1.traverse()
    assert res1.page_count == 1
    assert res1.outcome == FetchOutcome.PARTIAL
    assert res1.manifest.cursor_out is not None

    # Checkpoint exists in database
    chk = trav1.persistence.load_checkpoint(run_id, "resumable_src", f"{p}_{b}")
    assert chk is not None
    assert chk.pages_completed == 1
    assert chk.current_continuation == cont2

    # Run 2: resume=True, max_pages=5 to finish remaining pages
    trav2 = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(max_pages=5),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(raw_dir, ttl_seconds=0),
    )
    res2 = trav2.traverse(resume=True)

    # Continued from page 2 to terminal page
    assert res2.page_count == 1
    assert "job_2" in res2.manifest.observed_posting_identities
    # Traversal from start to terminal exhaustion across resumed segments is COMPLETE
    assert res2.manifest.outcome == FetchOutcome.COMPLETE
    assert res2.manifest.page_count == 2
    assert res2.manifest.observed_posting_identities == ["job_1", "job_2"]
    assert res2.manifest.cursor_out is None
