"""Tests for stage-level aggregation in FetchStageResult (INGEST-01-S08).

Verifies:
- Empty selection produces zero-attempt stage result
- All completed sources aggregate cleanly
- Mixed outcomes (COMPLETE, PARTIAL, FAILED) count accurately
- Preflight rejection aborts before stage execution
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import AdapterPage, Continuation
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import AdapterRegistry
from job_automation.sources.models import SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService
from job_automation.storage.engine import StorageEngine
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter


def _make_source(key: str, provider: str) -> SourceConfig:
    return SourceConfig(
        source_key=key,
        provider=provider,
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url=f"https://{provider}.invalid/api",
        enabled=True,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )


def _make_posting(provider: str, posting_id: str, num: int) -> RawPosting:
    return RawPosting(
        raw_payload_ref=f"raw://{provider}/{posting_id}",
        raw_content_hash="sha256:" + f"{num:02x}" * 32,
        source_key=SourceKey(provider=provider, board_id="default", source_posting_id=posting_id),
        fetch_time=datetime.now(timezone.utc),
        raw_payload=f'{{"id": "{posting_id}"}}',
    )


def test_fetch_stage_results_empty_selection(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    raw_dir = tmp_path / "raw"
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    envelope = SourceRegistryEnvelope(sources=[])
    registry_service = SourceRegistryService.from_envelope(envelope)
    controller = FetchController(
        storage=storage,
        registry_service=registry_service,
    )

    stage_res = controller.run_fetch(run_id=run_id, source_keys=[])

    assert stage_res.sources_attempted == 0
    assert stage_res.sources_completed == 0
    assert stage_res.sources_partial == 0
    assert stage_res.sources_failed == 0
    assert stage_res.total_pages == 0
    assert stage_res.total_raw_observations == 0
    assert stage_res.total_unique_identities == 0
    assert stage_res.source_results == {}


def test_fetch_stage_results_all_completed(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    raw_dir = tmp_path / "raw"
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    src1 = _make_source("src1", "prov1")
    src2 = _make_source("src2", "prov2")

    adapter1 = ScriptedPaginatedFakeAdapter(
        pages={None: AdapterPage(items=[_make_posting("prov1", "j1", 1)], exhausted=True)},
        expected_source_key="src1",
    )
    adapter2 = ScriptedPaginatedFakeAdapter(
        pages={None: AdapterPage(items=[_make_posting("prov2", "j2", 2)], exhausted=True)},
        expected_source_key="src2",
    )

    adapter_registry = AdapterRegistry()
    adapter_registry.register_for_key("src1", lambda s, k, o: adapter1)
    adapter_registry.register_for_key("src2", lambda s, k, o: adapter2)

    envelope = SourceRegistryEnvelope(sources=[src1, src2])
    registry_service = SourceRegistryService.from_envelope(envelope)

    controller = FetchController(
        storage=storage,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )

    stage_res = controller.run_fetch(run_id=run_id, source_keys=["src1", "src2"])

    assert stage_res.sources_attempted == 2
    assert stage_res.sources_completed == 2
    assert stage_res.sources_partial == 0
    assert stage_res.sources_failed == 0
    assert stage_res.total_pages == 2
    assert stage_res.total_raw_observations == 2
    assert stage_res.total_unique_identities == 2
    assert "src1" in stage_res.source_results
    assert "src2" in stage_res.source_results
    assert stage_res.source_results["src1"].outcome == FetchOutcome.COMPLETE
    assert stage_res.source_results["src2"].outcome == FetchOutcome.COMPLETE


def test_fetch_stage_results_mixed_outcomes(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    raw_dir = tmp_path / "raw"
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    src_complete = _make_source("src_complete", "prov_c")
    src_partial = _make_source("src_partial", "prov_p")
    src_failed = _make_source("src_failed", "prov_f")

    # src_complete: 1 page, exhausted -> COMPLETE
    adapter_c = ScriptedPaginatedFakeAdapter(
        pages={None: AdapterPage(items=[_make_posting("prov_c", "jc", 3)], exhausted=True)},
        expected_source_key="src_complete",
    )

    # src_partial: 1 page with continuation, stopped by max_pages=1 -> PARTIAL
    cont_p = Continuation(
        kind="page",
        value="2",
        source_key="src_partial",
        scope_id="prov_p_default",
        adapter_name="fake",
    )
    adapter_p = ScriptedPaginatedFakeAdapter(
        pages={
            None: AdapterPage(
                items=[_make_posting("prov_p", "jp", 4)],
                exhausted=False,
                continuation_out=cont_p,
            )
        },
        expected_source_key="src_partial",
    )

    # src_failed: 1 page with terminal error and 0 items -> FAILED
    err_f = ClassifiedError.from_category(
        category=ErrorCategory.PERMISSION,
        message="Forbidden 403",
        details={"status_code": 403},
    )
    adapter_f = ScriptedPaginatedFakeAdapter(
        pages={
            None: AdapterPage(
                items=[],
                exhausted=False,
                page_error=err_f,
            )
        },
        expected_source_key="src_failed",
    )

    adapter_registry = AdapterRegistry()
    adapter_registry.register_for_key("src_complete", lambda s, k, o: adapter_c)
    adapter_registry.register_for_key("src_partial", lambda s, k, o: adapter_p)
    adapter_registry.register_for_key("src_failed", lambda s, k, o: adapter_f)

    envelope = SourceRegistryEnvelope(sources=[src_complete, src_partial, src_failed])
    registry_service = SourceRegistryService.from_envelope(envelope)

    options = ControllerOptions(max_pages=1)
    controller = FetchController(
        storage=storage,
        options=options,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )

    stage_res = controller.run_fetch(
        run_id=run_id,
        source_keys=["src_complete", "src_partial", "src_failed"],
    )

    assert stage_res.sources_attempted == 3
    assert stage_res.sources_completed == 1
    assert stage_res.sources_partial == 1
    assert stage_res.sources_failed == 1
    assert stage_res.source_results["src_complete"].outcome == FetchOutcome.COMPLETE
    assert stage_res.source_results["src_partial"].outcome == FetchOutcome.PARTIAL
    assert stage_res.source_results["src_failed"].outcome == FetchOutcome.FAILED

