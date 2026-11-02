"""Tests for multi-source runtime failure isolation (INGEST-01-S08).

CRITICAL INVARIANT: One source's failure must never erase, rollback, or invalidate
another independent source's results.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import AdapterPage
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import AdapterRegistry
from job_automation.sources.models import EffectiveSource, SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService
from job_automation.sources.validation import validate_source_config
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


def test_independent_source_failure_isolation(tmp_path: Path):
    db_path = tmp_path / "iso" / "data.db"
    raw_dir = tmp_path / "iso" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    src_a = _make_source("src_a", "prov_a")
    src_b = _make_source("src_b", "prov_b")
    src_c = _make_source("src_c", "prov_c")

    envelope = SourceRegistryEnvelope(sources=[src_a, src_b, src_c])
    registry_service = SourceRegistryService.from_envelope(envelope)

    # Source A: succeeds with 1 item
    page_a = AdapterPage(
        items=[_make_posting("prov_a", "job_a_1", 1)],
        issues=[],
        exhausted=True,
    )
    adapter_a = ScriptedPaginatedFakeAdapter(pages={None: page_a}, expected_source_key="src_a")

    # Source B: fails with 403 Forbidden error
    err_b = ClassifiedError.from_category(
        category=ErrorCategory.PERMISSION,
        message="403 Forbidden",
        details={"status_code": 403},
    )
    page_b = AdapterPage(
        items=[],
        issues=[],
        exhausted=True,
        page_error=err_b,
    )
    adapter_b = ScriptedPaginatedFakeAdapter(pages={None: page_b}, expected_source_key="src_b")

    # Source C: succeeds with 1 item
    page_c = AdapterPage(
        items=[_make_posting("prov_c", "job_c_1", 3)],
        issues=[],
        exhausted=True,
    )
    adapter_c = ScriptedPaginatedFakeAdapter(pages={None: page_c}, expected_source_key="src_c")

    # Wire adapter registry
    adapter_reg = AdapterRegistry()
    adapter_reg.register_for_key("src_a", lambda s, k, o: adapter_a)
    adapter_reg.register_for_key("src_b", lambda s, k, o: adapter_b)
    adapter_reg.register_for_key("src_c", lambda s, k, o: adapter_c)

    controller = FetchController(
        storage=storage,
        registry_service=registry_service,
        options=ControllerOptions(),
        adapter_registry=adapter_reg,
    )

    stage_result = controller.run_fetch(run_id, source_keys=["src_a", "src_b", "src_c"])

    # Stage counters
    assert stage_result.sources_attempted == 3
    assert stage_result.sources_completed == 2
    assert stage_result.sources_failed == 1
    assert stage_result.sources_partial == 0

    # Source A verified
    res_a = stage_result.source_results["src_a"]
    assert res_a.outcome == FetchOutcome.COMPLETE
    assert res_a.observed_identities_count == 1
    assert "job_a_1" in res_a.manifest.observed_posting_identities

    # Source B verified
    res_b = stage_result.source_results["src_b"]
    assert res_b.outcome == FetchOutcome.FAILED
    assert res_b.manifest.error is not None
    assert res_b.manifest.error.category == ErrorCategory.PERMISSION

    # Source C verified
    res_c = stage_result.source_results["src_c"]
    assert res_c.outcome == FetchOutcome.COMPLETE
    assert res_c.observed_identities_count == 1
    assert "job_c_1" in res_c.manifest.observed_posting_identities

    # CRITICAL INVARIANT: Verify database state!
    # Source A and Source C's raw postings MUST exist in the database!
    raw_a = storage.raw_postings.get_raw_posting(SourceKey(provider="prov_a", board_id="default", source_posting_id="job_a_1"))
    raw_c = storage.raw_postings.get_raw_posting(SourceKey(provider="prov_c", board_id="default", source_posting_id="job_c_1"))
    assert raw_a is not None
    assert raw_c is not None

    # All three manifests must be durably stored in the database
    manifests = storage.raw_postings.get_manifests_for_run(run_id)
    manifest_map = {m.source_key: m for m in manifests}
    assert "src_a" in manifest_map
    assert "src_b" in manifest_map
    assert "src_c" in manifest_map
    assert manifest_map["src_a"].outcome == FetchOutcome.COMPLETE
    assert manifest_map["src_b"].outcome == FetchOutcome.FAILED
    assert manifest_map["src_c"].outcome == FetchOutcome.COMPLETE

