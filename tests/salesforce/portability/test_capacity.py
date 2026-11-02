"""Unit and contract tests for Salesforce org capacity observation and headroom decisions (SF-04-S01)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from job_automation.contracts.salesforce import LimitsResult
from job_automation.salesforce.capacity import (
    evaluate_capacity_decision,
    observe_capacity_from_limits,
    parse_resource_metrics,
    query_and_observe_capacity,
)
from job_automation.salesforce.portability_settings import CapacityPolicySettings
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.fixtures.salesforce.portability.limits_fixtures import (
    SYNTHETIC_LIMITS_EXHAUSTED,
    SYNTHETIC_LIMITS_HEALTHY,
    SYNTHETIC_LIMITS_INCONSISTENT,
    SYNTHETIC_LIMITS_TIGHT,
    SYNTHETIC_LIMITS_ZERO_MAX,
)


class TestCapacityObservation:
    def test_used_equals_max_minus_remaining(self) -> None:
        """A synthetic maximum of 100 and remaining 25 reports used 75."""
        res = parse_resource_metrics(
            name="daily_api_requests",
            unit="requests",
            max_val=100,
            remaining_val=25,
            reserve_abs=10,
            reserve_pct=5.0,
            warning_multiplier=2.0,
        )
        assert res.max_value == 100.0
        assert res.remaining_value == 25.0
        assert res.used_value == 75.0
        assert res.percent_used == 75.0
        assert res.status == "ok"  # 25 > 20 (warning threshold = 10 * 2)

    def test_zero_maximum_never_divides_by_zero(self) -> None:
        """Zero maximum is explicitly unknown/unavailable, never division by zero."""
        res = parse_resource_metrics(
            name="data_storage_mb",
            unit="MB",
            max_val=0,
            remaining_val=0,
            reserve_abs=5.0,
            reserve_pct=10.0,
            warning_multiplier=2.0,
        )
        assert res.status == "unknown"
        assert res.used_value is None
        assert res.percent_used is None
        assert "zero or negative" in (res.reason or "")

    def test_inconsistent_values_produce_unknown_status(self) -> None:
        """Negative remaining or remaining > max produces unknown status."""
        res_neg = parse_resource_metrics(
            name="daily_api_requests",
            unit="requests",
            max_val=100,
            remaining_val=-5,
            reserve_abs=10,
            reserve_pct=5.0,
            warning_multiplier=2.0,
        )
        assert res_neg.status == "unknown"

        res_over = parse_resource_metrics(
            name="daily_api_requests",
            unit="requests",
            max_val=100,
            remaining_val=150,
            reserve_abs=10,
            reserve_pct=5.0,
            warning_multiplier=2.0,
        )
        assert res_over.status == "unknown"

    def test_missing_filestorage_never_becomes_unlimited(self) -> None:
        """Missing FileStorage is reported as unknown, never healthy or unlimited."""
        settings = CapacityPolicySettings(data_storage_reserve_mb=2.0)
        limits = LimitsResult(
            daily_api_requests_max=15000,
            daily_api_requests_remaining=14000,
            raw_limits={"DataStorageMB": {"Max": 100, "Remaining": 80}},
        )
        obs = observe_capacity_from_limits(
            limits_result=limits,
            org_id="00D000000000001",
            api_version="60.0",
            settings=settings,
        )
        assert "file_storage_mb" in obs.resources
        assert obs.resources["file_storage_mb"].status == "unknown"
        assert obs.overall_status == "unknown"

    def test_two_synthetic_orgs_produce_different_headroom_decisions(self) -> None:
        """Two synthetic orgs with different headroom produce distinct decisions."""
        settings = CapacityPolicySettings(
            data_storage_reserve_mb=2.0,
            data_storage_reserve_percent=10.0,
            api_requests_reserve=20,
            api_requests_reserve_percent=10.0,
        )

        # Org A: Healthy (DataStorage 80 MB remaining > 10 MB reserve)
        limits_a = LimitsResult(
            daily_api_requests_max=SYNTHETIC_LIMITS_HEALTHY["DailyApiRequests"]["Max"],
            daily_api_requests_remaining=SYNTHETIC_LIMITS_HEALTHY["DailyApiRequests"]["Remaining"],
            raw_limits=SYNTHETIC_LIMITS_HEALTHY,
        )
        obs_a = observe_capacity_from_limits(
            limits_result=limits_a,
            org_id="00DOrgA000000001",
            api_version="60.0",
            settings=settings,
        )
        dec_a = evaluate_capacity_decision(
            observation=obs_a,
            operation_kind="publication",
            settings=settings,
            planned_records=10,
        )
        assert dec_a.allowed is True
        assert dec_a.status == "ok"

        # Org B: Tight (DataStorage 0 MB remaining < 2.0 MB reserve -> Blocked)
        limits_b = LimitsResult(
            daily_api_requests_max=SYNTHETIC_LIMITS_TIGHT["DailyApiRequests"]["Max"],
            daily_api_requests_remaining=SYNTHETIC_LIMITS_TIGHT["DailyApiRequests"]["Remaining"],
            raw_limits=SYNTHETIC_LIMITS_TIGHT,
        )
        obs_b = observe_capacity_from_limits(
            limits_result=limits_b,
            org_id="00DOrgB000000001",
            api_version="60.0",
            settings=settings,
        )
        dec_b = evaluate_capacity_decision(
            observation=obs_b,
            operation_kind="publication",
            settings=settings,
            planned_records=10,
        )
        assert dec_b.allowed is False
        assert dec_b.status == "blocked"

    def test_export_read_allowed_when_data_storage_blocked(self) -> None:
        """Read-only export does not require data storage write headroom."""
        settings = CapacityPolicySettings(data_storage_reserve_mb=2.0)
        limits = LimitsResult(
            daily_api_requests_max=1000,
            daily_api_requests_remaining=900,
            raw_limits={
                "DailyApiRequests": {"Max": 1000, "Remaining": 900},
                "DataStorageMB": {"Max": 5, "Remaining": 0},  # Blocked for write
                "FileStorageMB": {"Max": 10, "Remaining": 8},
            },
        )
        obs = observe_capacity_from_limits(
            limits_result=limits,
            org_id="00D000000000001",
            api_version="60.0",
            settings=settings,
        )

        dec_read = evaluate_capacity_decision(
            observation=obs,
            operation_kind="export_read",
            settings=settings,
            planned_calls=5,
        )
        assert dec_read.allowed is True
        assert dec_read.status == "ok"

    def test_stale_evidence_returns_unknown_decision(self) -> None:
        """Observations older than freshness_hours must not authorize operations."""
        settings = CapacityPolicySettings(freshness_hours=1.0)
        old_time = datetime.now(timezone.utc) - timedelta(hours=2.5)

        limits = LimitsResult(
            daily_api_requests_max=15000,
            daily_api_requests_remaining=14000,
            raw_limits=SYNTHETIC_LIMITS_HEALTHY,
        )
        obs = observe_capacity_from_limits(
            limits_result=limits,
            org_id="00D000000000001",
            api_version="60.0",
            settings=settings,
            measured_at=old_time,
        )

        decision = evaluate_capacity_decision(
            observation=obs,
            operation_kind="publication",
            settings=settings,
        )
        assert decision.allowed is False
        assert decision.status == "unknown"
        assert "stale" in decision.reason
