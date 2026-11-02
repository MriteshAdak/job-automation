"""Tests for request limits, page budgets, deadlines, and rate limiting (INGEST-01-S04)."""

import pytest

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import ClockProtocol, SleeperProtocol
from job_automation.ingestion.request_control import DomainRateLimiter, RequestBudget
from job_automation.sources.models import EffectiveSource
from job_automation.sources.validation import validate_source_config


class FakeClock(ClockProtocol):
    def __init__(self, start: float = 1000.0) -> None:
        self._time = start

    def now_utc(self):
        raise NotImplementedError

    def monotonic(self) -> float:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += seconds


class FakeSleeper(SleeperProtocol):
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.advance(seconds)


def _make_source_with_policy(max_pages: int | None = None, timeout: float | None = None) -> EffectiveSource:
    policy_dict = {}
    if max_pages is not None:
        policy_dict["max_pages"] = max_pages
    if timeout is not None:
        policy_dict["timeout_seconds"] = timeout

    cfg = SourceConfig(
        source_key="budget_test",
        provider="test_prov",
        board_id="default",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        request_policy=policy_dict,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    return validate_source_config(cfg)


def test_request_budget_stricter_cap_precedence():
    clock = FakeClock(100.0)
    opts = ControllerOptions(max_pages=15, timeout_seconds=40.0)

    # Source has stricter max_pages (5 < 15) and stricter timeout (20 < 40)
    source = _make_source_with_policy(max_pages=5, timeout=20.0)
    budget = RequestBudget.from_source_and_options(source, opts, clock.monotonic())

    assert budget.max_pages == 5
    assert budget.remaining_pages == 5
    assert budget.timeout_seconds == 20.0


def test_request_budget_consumption_and_deadline():
    clock = FakeClock(100.0)
    opts = ControllerOptions(max_pages=2, max_requests=3, source_deadline_seconds=50.0)
    source = _make_source_with_policy()
    budget = RequestBudget.from_source_and_options(source, opts, clock.monotonic())

    assert budget.has_requests()
    assert budget.has_pages()
    assert not budget.is_deadline_exceeded(clock.monotonic())

    budget.consume_request()
    assert budget.remaining_requests == 2
    budget.consume_request()
    budget.consume_request()
    assert not budget.has_requests()

    # Advance clock past deadline (100 + 50 = 150)
    clock.advance(60.0)
    assert budget.is_deadline_exceeded(clock.monotonic())


def test_domain_rate_limiter_spacing():
    clock = FakeClock(100.0)
    sleeper = FakeSleeper(clock)
    limiter = DomainRateLimiter()

    # First request has no prior request: delay is 0
    delay1 = limiter.enforce_spacing("domain1", 10.0, clock, sleeper)
    assert delay1 == 0.0
    assert len(sleeper.sleeps) == 0

    # Advance clock by 3 seconds; needed spacing is 10 - 3 = 7 seconds
    clock.advance(3.0)
    delay2 = limiter.enforce_spacing("domain1", 10.0, clock, sleeper)
    assert delay2 == 7.0
    assert sleeper.sleeps == [7.0]

    # Different domain is independent
    delay3 = limiter.enforce_spacing("domain2", 10.0, clock, sleeper)
    assert delay3 == 0.0

