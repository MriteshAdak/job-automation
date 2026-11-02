"""Shared helpers and fixtures for Arbeitnow adapter tests (SOURCE-03-arbeitnow).

Provides:
  - FakeTransport: scripted HTTP responses, no real networking
  - FakeClock: deterministic UTC datetime
  - build_arbeitnow_source(): valid EffectiveSource for arbeitnow_de
  - FIXTURE_DIR: path to tests/fixtures/sources/arbeitnow/
  - load_fixture(): read fixture bytes as UTF-8
  - FAIL_ON_NETWORK: marks tests that must not reach real network
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sources" / "arbeitnow"

FIXED_UTC = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    """Injected clock returning a fixed UTC datetime."""

    def __init__(self, dt: datetime = FIXED_UTC) -> None:
        self._dt = dt

    def now_utc(self) -> datetime:
        return self._dt


class FakeTransport:
    """Scripted HTTP transport — no real networking."""

    def __init__(self, responses: dict[str, tuple[int, dict[str, str], bytes]] | None = None) -> None:
        # responses keyed by URL; default 200 empty JSON if not found
        self._responses = responses or {}
        self.calls: list[str] = []

    def add(self, url: str, status: int, headers: dict[str, str], body: bytes) -> None:
        self._responses[url] = (status, headers, body)

    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        self.calls.append(url)
        if url in self._responses:
            return self._responses[url]
        # Default: 404 not found
        return 404, {}, b'{"error":"not_found"}'


class FailOnNetworkTransport:
    """Transport that raises RuntimeError if called — used to guard against real I/O."""

    def get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        raise RuntimeError(f"REAL NETWORK CALL DETECTED: {url}")


def load_fixture(name: str) -> bytes:
    """Load a fixture file as bytes (UTF-8 encoding guaranteed by write)."""
    path = FIXTURE_DIR / name
    return path.read_bytes()


def load_fixture_json(name: str) -> Any:
    """Load and parse a fixture file as JSON."""
    return json.loads(load_fixture(name).decode("utf-8"))


def build_arbeitnow_config(
    enabled: bool = True,
    inventory_semantics: InventorySemantics = InventorySemantics.FILTERED_FEED,
    provider: str = "arbeitnow",
    board_id: str = "default",
) -> SourceConfig:
    """Build a SourceConfig for the Arbeitnow adapter."""
    return SourceConfig(
        source_key="arbeitnow_de",
        provider=provider,
        board_id=board_id,
        acquisition_method=AcquisitionMethod.API,
        base_url="https://www.arbeitnow.com/api/job-board-api",
        access_rules=None,
        attribution_rules=None,
        request_policy={"timeout_seconds": 30.0},
        enabled=enabled,
        inventory_semantics=inventory_semantics,
    )


def build_arbeitnow_source(
    enabled: bool = True,
    access_status: AccessReviewStatus = AccessReviewStatus.PERMITTED,
    attribution_status: AttributionStatus = AttributionStatus.REQUIRED,
    inventory_semantics: InventorySemantics = InventorySemantics.FILTERED_FEED,
    provider: str = "arbeitnow",
    board_id: str = "default",
    scope_id: str = "scope-v1:arbeitnow-default-filtered",
) -> EffectiveSource:
    """Build a valid EffectiveSource for the Arbeitnow adapter."""
    config = build_arbeitnow_config(
        enabled=enabled,
        inventory_semantics=inventory_semantics,
        provider=provider,
        board_id=board_id,
    )
    return EffectiveSource(
        config=config,
        access_review=AccessReview(
            status=access_status,
            reviewed_at="2026-10-28T00:00:00Z",
            evidence_ref="E3-arbeitnow-terms-section-11",
            permitted_methods=[AcquisitionMethod.API],
            restrictions=["as_available_basis", "link_back_required"],
        ),
        attribution_review=AttributionReview(
            status=attribution_status,
            notice="Source: Arbeitnow",
            link="https://www.arbeitnow.com",
        ),
        request_policy=EffectiveRequestPolicy(
            timeout_seconds=30.0,
            max_attempts=1,
        ),
        inventory_scope=InventoryScope(
            scope_id=scope_id,
            semantics=inventory_semantics,
            provider=provider,
            board_id=board_id,
            acquisition_method=AcquisitionMethod.API,
            base_url="https://www.arbeitnow.com/api/job-board-api",
        ),
        is_valid=True,
        is_runnable=enabled and access_status == AccessReviewStatus.PERMITTED,
    )


def build_adapter(
    transport: Any | None = None,
    clock: Any | None = None,
    source: EffectiveSource | None = None,
    sink: InMemoryRawCaptureSink | None = None,
) -> tuple[ArbeitnowAdapter, InMemoryRawCaptureSink]:
    """Build an ArbeitnowAdapter with injected fakes."""
    if source is None:
        source = build_arbeitnow_source()
    if sink is None:
        sink = InMemoryRawCaptureSink()
    if transport is None:
        transport = FailOnNetworkTransport()
    if clock is None:
        clock = FakeClock()
    adapter = ArbeitnowAdapter(
        effective_source=source,
        capture_sink=sink,
        transport=transport,
        clock=clock,
    )
    return adapter, sink

