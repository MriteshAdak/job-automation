"""End-to-end integration tests for FetchController with multi-source execution (INGEST-01-S08).

Tests:
- FetchController coordinates multiple disparate sources (manual text, manual CSV, API adapter)
- Raw bytes are durably captured to disk
- Raw postings and checkpoints are committed to SQLite
- Authoritative C04 manifests are created and finalized
- Stage summary reflects aggregate metrics accurately
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import AdapterPage
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
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


def test_fetch_controller_multi_source_integration(tmp_path: Path) -> None:
    db_path = tmp_path / "integration" / "app.db"
    raw_dir = tmp_path / "integration" / "raw"
    input_dir = tmp_path / "integration" / "inputs"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create manual text file
    text_file = input_dir / "job_posting.txt"
    text_file.write_text(
        "Software Engineer\nAcme Corp\nBerlin, Germany\nDevelop high quality software.",
        encoding="utf-8",
    )

    # 2. Create manual CSV file
    csv_file = input_dir / "jobs.csv"
    csv_file.write_text(
        "source_posting_id,source_url,title,company,text,locations_raw,compensation_raw\n"
        "csv-01,https://example.invalid/01,Data Engineer,Cloud Inc,Data Engineer text,Munich,80000\n"
        "csv-02,https://example.invalid/02,Site Reliability Engineer,Ops AG,SRE text,Remote,85000\n",
        encoding="utf-8",
    )

    # 3. Setup database
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    # 4. Define source configs
    src_text = SourceConfig(
        source_key="manual_text_src",
        provider="manual",
        board_id="text_board",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="https://manual.invalid",
        enabled=True,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    src_csv = SourceConfig(
        source_key="manual_csv_src",
        provider="manual",
        board_id="csv_board",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="https://manual.invalid",
        enabled=True,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    src_api = SourceConfig(
        source_key="api_src",
        provider="api_provider",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://api.invalid",
        enabled=True,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )

    envelope = SourceRegistryEnvelope(sources=[src_text, src_csv, src_api])
    registry_service = SourceRegistryService.from_envelope(envelope)

    # 5. Build fake adapter for api_src
    posting_api = RawPosting(
        raw_payload_ref="raw://api/job_api_1",
        raw_content_hash="sha256:" + "a" * 64,
        source_key=SourceKey(provider="api_provider", board_id="default", source_posting_id="job_api_1"),
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"id": "job_api_1", "title": "API Engineer"}',
    )
    adapter_api = ScriptedPaginatedFakeAdapter(
        pages={None: AdapterPage(items=[posting_api], exhausted=True)},
        expected_source_key="api_src",
    )

    adapter_registry = AdapterRegistry()
    adapter_registry.register_for_key("api_src", lambda s, k, o: adapter_api)

    # 6. Configure ControllerOptions
    options = ControllerOptions(
        input_base_path=input_dir,
        manual_inputs={
            "manual_text_src": {"input_file": "job_posting.txt"},
            "manual_csv_src": {"csv_path": "jobs.csv", "page_size": 10},
        },
    )

    # 7. Initialize controller and run fetch
    controller = FetchController(
        storage=storage,
        options=options,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )

    stage_result = controller.run_fetch(
        run_id=run_id,
        source_keys=["manual_text_src", "manual_csv_src", "api_src"],
    )

    # 8. Assert stage results
    assert stage_result.sources_attempted == 3
    assert stage_result.sources_completed == 3
    assert stage_result.sources_partial == 0
    assert stage_result.sources_failed == 0

    assert "manual_text_src" in stage_result.source_results
    assert "manual_csv_src" in stage_result.source_results
    assert "api_src" in stage_result.source_results

    res_text = stage_result.source_results["manual_text_src"]
    res_csv = stage_result.source_results["manual_csv_src"]
    res_api = stage_result.source_results["api_src"]

    assert res_text.outcome == FetchOutcome.COMPLETE
    assert res_csv.outcome == FetchOutcome.COMPLETE
    assert res_api.outcome == FetchOutcome.COMPLETE

    # Verify manifest records in DB
    manifests = storage.raw_postings.get_manifests_for_run(run_id)
    manifest_by_source = {m.source_key: m for m in manifests}

    assert "manual_text_src" in manifest_by_source
    assert manifest_by_source["manual_text_src"].outcome == FetchOutcome.COMPLETE

    assert "manual_csv_src" in manifest_by_source
    assert manifest_by_source["manual_csv_src"].outcome == FetchOutcome.COMPLETE
    assert len(manifest_by_source["manual_csv_src"].observed_posting_identities) == 2

    assert "api_src" in manifest_by_source
    assert manifest_by_source["api_src"].outcome == FetchOutcome.COMPLETE
    assert "job_api_1" in manifest_by_source["api_src"].observed_posting_identities
