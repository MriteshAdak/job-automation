"""Unit and contract boundary tests for INGEST-01 models and ports (INGEST-01-S01)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.models import (
    AttemptRecord,
    CacheEntry,
    ControllerOptions,
    FetchStageResult,
    PageReceipt,
    SourceCheckpoint,
    SourceFetchResult,
)
from job_automation.ingestion.ports import AdapterRegistry, SystemClock, SystemSleeper
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveSource,
)


from job_automation.sources.validation import validate_source_config


def _make_dummy_effective_source(source_key: str = "test_src", provider: str = "test_prov") -> EffectiveSource:
    cfg = SourceConfig(
        source_key=source_key,
        provider=provider,
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted"}',
        attribution_rules='{"status": "none_required"}',
    )
    return validate_source_config(cfg)


def test_controller_options_defaults_and_validation():
    opts = ControllerOptions()
    assert opts.max_pages == 10
    assert opts.max_requests == 20
    assert opts.max_attempts_per_page == 3
    assert opts.timeout_seconds == 30.0
    assert opts.source_deadline_seconds == 300.0
    assert opts.max_response_bytes == 10 * 1024 * 1024
    assert opts.cache_mode == "disabled"
    assert opts.cache_ttl_seconds == 0

    # Reject boolean as int
    with pytest.raises(ValidationError):
        ControllerOptions(max_pages=True)  # type: ignore

    # Reject non-positive caps
    with pytest.raises(ValidationError):
        ControllerOptions(max_pages=0)

    # Reject unsupported cache_mode
    with pytest.raises(ValidationError):
        ControllerOptions(cache_mode="invalid_mode")

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        ControllerOptions(extra_unknown_field=123)  # type: ignore


def test_attempt_record_model():
    now = datetime.now(timezone.utc)
    att = AttemptRecord(
        attempt_number=1,
        started_at=now,
        duration_ms=123.4,
        status_code=200,
        retry_after_seconds=5.0,
    )
    assert att.attempt_number == 1
    assert att.duration_ms == 123.4
    dump = att.model_dump(mode="json")
    loaded = AttemptRecord.model_validate(dump)
    assert loaded.attempt_number == att.attempt_number


def test_page_receipt_model_round_trip():
    now = datetime.now(timezone.utc)
    cont = Continuation(
        kind="page",
        value="2",
        source_key="src1",
        scope_id="prov1_board1",
        adapter_name="test-v1",
    )
    receipt = PageReceipt(
        traversal_id="trav_123",
        page_index=1,
        attempt_count=1,
        continuation_in=None,
        continuation_out=cont,
        source_key="src1",
        scope_id="prov1_board1",
        adapter_name="test-v1",
        raw_response_refs=["raw://1"],
        raw_response_hashes=["sha256:abc"],
        observed_posting_ids=["job_001"],
        fetch_time=now,
        exhausted=False,
    )
    dump = receipt.model_dump(mode="json")
    loaded = PageReceipt.model_validate(dump)
    assert loaded.traversal_id == "trav_123"
    assert loaded.page_index == 1
    assert loaded.observed_posting_ids == ["job_001"]


def test_source_checkpoint_model_round_trip():
    now = datetime.now(timezone.utc)
    chk = SourceCheckpoint(
        traversal_id="trav_123",
        run_id=uuid.uuid4(),
        source_key="src1",
        scope_id="prov1_board1",
        adapter_name="test-v1",
        current_continuation=None,
        visited_tokens=["cont-v1:abc"],
        pages_completed=2,
        records_observed=["job_001", "job_002"],
        raw_response_refs=["ref1", "ref2"],
        requests_made=2,
        created_at=now,
        updated_at=now,
    )
    dump = chk.model_dump(mode="json")
    loaded = SourceCheckpoint.model_validate(dump)
    assert loaded.pages_completed == 2
    assert loaded.records_observed == ["job_001", "job_002"]


def test_fetch_stage_result_model():
    run_id = uuid.uuid4()
    stage = FetchStageResult(
        run_id=run_id,
        sources_attempted=2,
        sources_completed=1,
        sources_partial=1,
        total_requests=5,
        total_pages=3,
        total_raw_observations=10,
        total_unique_identities=8,
    )
    assert stage.sources_attempted == 2
    assert stage.total_requests == 5


def test_adapter_registry_unknown_source_raises():
    registry = AdapterRegistry()
    eff = _make_dummy_effective_source(source_key="unregistered_key", provider="unregistered_prov")
    sink = InMemoryRawCaptureSink()
    opts = ControllerOptions()

    with pytest.raises(ValueError, match="No registered adapter factory"):
        registry.create_adapter(eff, sink, opts)


def test_adapter_registry_custom_registration():
    registry = AdapterRegistry()
    eff = _make_dummy_effective_source(source_key="custom_src", provider="custom_prov")
    sink = InMemoryRawCaptureSink()
    opts = ControllerOptions()

    class FakeAdapterImpl:
        def fetch_page(self, config, continuation=None):
            raise NotImplementedError
        def draft_posting(self, raw):
            raise NotImplementedError

    registry.register_for_key("custom_src", lambda s, k, o: FakeAdapterImpl())
    adapter = registry.create_adapter(eff, sink, opts)
    assert isinstance(adapter, FakeAdapterImpl)


def test_clock_and_sleeper_protocols():
    clock = SystemClock()
    assert clock.now_utc().tzinfo == timezone.utc
    assert isinstance(clock.monotonic(), float)

    sleeper = SystemSleeper()
    # sleep 0 does not block
    sleeper.sleep(0.0)
