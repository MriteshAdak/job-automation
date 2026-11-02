"""Tests asserting INGEST-01 boundaries: no deduplication, no job closure inference (INGEST-01-S07)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.adapter_results import AdapterPage
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.pagination import PaginationTraverser
from job_automation.ingestion.ports import SystemClock, SystemSleeper
from job_automation.ingestion.request_control import DomainRateLimiter
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def test_ingest_does_not_mutate_canonical_jobs_or_infer_closure(tmp_path: Path):
    db_path = tmp_path / "bound" / "data.db"
    raw_dir = tmp_path / "bound" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    # Pre-populate canonical jobs table with an active job
    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    job = CanonicalJob(
        canonical_job_id=job_id,
        company_name="Acme Corp",
        availability="active",
        current_revision_id=uuid.uuid4(),
        first_seen_at=now,
        last_seen_at=now,
    )
    storage.canonical_jobs.save_canonical_job(job)

    # Execute empty feed in INGEST-01
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    cfg = SourceConfig(
        source_key="empty_src",
        provider="empty_prov",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    eff = validate_source_config(cfg)
    sink = DurableRawCaptureSink(raw_dir)

    empty_page = AdapterPage(items=[], issues=[], continuation_in=None, continuation_out=None, exhausted=True)
    adapter = ScriptedPaginatedFakeAdapter(pages={None: empty_page}, expected_source_key="empty_src")

    traverser = PaginationTraverser(
        run_id=run_id,
        effective_source=eff,
        adapter=adapter,
        storage=storage,
        sink=sink,
        options=ControllerOptions(),
        clock=SystemClock(),
        sleeper=SystemSleeper(),
        rate_limiter=DomainRateLimiter(),
        cache=PageCache(raw_dir, ttl_seconds=0),
    )
    res = traverser.traverse()

    assert res.outcome == FetchOutcome.COMPLETE
    assert res.observed_identities_count == 0

    # BOUNDARY ASSERTION: Canonical jobs table must be completely untouched!
    reloaded_job = storage.canonical_jobs.get_canonical_job(job_id)
    assert reloaded_job is not None
    assert reloaded_job.availability.value == "active"

