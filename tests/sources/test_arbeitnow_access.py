"""Access and binding validation tests for ArbeitnowAdapter (SOURCE-03-S01)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from job_automation.sources.models import AccessReviewStatus, AttributionStatus
from tests.sources.arbeitnow_helpers import (
    FailOnNetworkTransport,
    FakeClock,
    build_adapter,
    build_arbeitnow_config,
    build_arbeitnow_source,
)


def test_valid_arbeitnow_source_binds_successfully() -> None:
    source = build_arbeitnow_source(enabled=True)
    adapter, sink = build_adapter(source=source)
    assert isinstance(adapter, ArbeitnowAdapter)


def test_construction_performs_no_network_calls() -> None:
    source = build_arbeitnow_source(enabled=True)
    transport = FailOnNetworkTransport()
    # If construction attempted any network calls, FailOnNetworkTransport would raise
    adapter = ArbeitnowAdapter(
        effective_source=source,
        capture_sink=InMemoryRawCaptureSink(),
        transport=transport,
        clock=FakeClock(),
    )
    assert adapter is not None


def test_disabled_source_raises_value_error() -> None:
    source = build_arbeitnow_source(enabled=False)
    with pytest.raises(ValueError, match="is disabled"):
        build_adapter(source=source)


@pytest.mark.parametrize(
    "access_status",
    [AccessReviewStatus.UNREVIEWED, AccessReviewStatus.DENIED],
)
def test_unpermitted_access_status_raises_value_error(
    access_status: AccessReviewStatus,
) -> None:
    source = build_arbeitnow_source(enabled=True, access_status=access_status)
    with pytest.raises(ValueError, match="must be 'permitted'"):
        build_adapter(source=source)


def test_wrong_provider_raises_value_error() -> None:
    source = build_arbeitnow_source(enabled=True, provider="other_provider")
    with pytest.raises(ValueError, match="requires provider 'arbeitnow'"):
        build_adapter(source=source)


def test_wrong_board_id_raises_value_error() -> None:
    source = build_arbeitnow_source(enabled=True, board_id="germany_remote")
    with pytest.raises(ValueError, match="requires board_id 'default'"):
        build_adapter(source=source)


def test_complete_board_semantics_raises_value_error() -> None:
    source = build_arbeitnow_source(
        enabled=True,
        inventory_semantics=InventorySemantics.COMPLETE_BOARD,
    )
    with pytest.raises(ValueError, match="does not support 'complete_board' semantics"):
        build_adapter(source=source)


def test_unknown_attribution_status_raises_value_error() -> None:
    source = build_arbeitnow_source(
        enabled=True,
        attribution_status=AttributionStatus.UNKNOWN,
    )
    with pytest.raises(ValueError, match="requires attribution_review.status"):
        build_adapter(source=source)


def test_runtime_config_mismatch_returns_validation_error() -> None:
    adapter, _ = build_adapter()
    mismatched_config = build_arbeitnow_config().model_copy(
        update={"source_key": "different_source_key"}
    )

    page = adapter.fetch_page(mismatched_config)

    assert page.page_error is not None
    assert page.page_error.category == ErrorCategory.VALIDATION
    assert "does not match" in page.page_error.message
    assert page.record_count == 0
    assert not page.exhausted
