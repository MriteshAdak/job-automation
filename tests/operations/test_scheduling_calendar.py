"""Unit tests for calendar slot calculation, Berlin DST gap/fold resolution, and missed-run coalescing (AUTO-01-T07, T09)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from job_automation.operations.scheduling.calendar import CalendarCalculator
from job_automation.operations.scheduling.records import (
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleOccurrence,
)


def test_berlin_winter_and_summer_slots():
    """T07: 07:00 Berlin maps to 06:00 UTC in winter (CET) and 05:00 UTC in summer (CEST)."""
    calc = CalendarCalculator("Europe/Berlin")

    # Winter (15 January 2027)
    winter_slot = calc.resolve_slot(date(2027, 1, 15), "07:00")
    assert winter_slot.intended_slot_key == "2027-01-15T07:00:00 Europe/Berlin"
    assert winter_slot.intended_utc_instant == datetime(2027, 1, 15, 6, 0, tzinfo=timezone.utc)
    assert winter_slot.local_offset_minutes == 60
    assert winter_slot.fold == 0
    assert winter_slot.is_gap_adjusted is False

    # Summer (15 July 2027)
    summer_slot = calc.resolve_slot(date(2027, 7, 15), "07:00")
    assert summer_slot.intended_slot_key == "2027-07-15T07:00:00 Europe/Berlin"
    assert summer_slot.intended_utc_instant == datetime(2027, 7, 15, 5, 0, tzinfo=timezone.utc)
    assert summer_slot.local_offset_minutes == 120
    assert summer_slot.fold == 0
    assert summer_slot.is_gap_adjusted is False


def test_spring_gap_resolution_2027():
    """T07: Synthetic 02:30 slot on 28 March 2027 moves to 03:00 CEST (01:00 UTC), retaining 02:30 intent."""
    calc = CalendarCalculator("Europe/Berlin")

    gap_slot = calc.resolve_slot(date(2027, 3, 28), "02:30")
    assert gap_slot.intended_slot_key == "2027-03-28T02:30:00 Europe/Berlin"
    assert gap_slot.is_gap_adjusted is True
    assert gap_slot.adjusted_local_time == "03:00"
    # In Europe/Berlin on 28 March 2027, 03:00 CEST is 01:00 UTC
    assert gap_slot.intended_utc_instant == datetime(2027, 3, 28, 1, 0, tzinfo=timezone.utc)
    assert gap_slot.local_offset_minutes == 120


def test_autumn_fold_resolution_2027():
    """T07: Synthetic 02:30 slot on 31 October 2027 admits once at earlier occurrence (fold=0, 00:30 UTC)."""
    calc = CalendarCalculator("Europe/Berlin")

    fold_slot = calc.resolve_slot(date(2027, 10, 31), "02:30")
    assert fold_slot.intended_slot_key == "2027-10-31T02:30:00 Europe/Berlin"
    assert fold_slot.fold == 0
    assert fold_slot.is_gap_adjusted is False
    # Earlier occurrence (CEST, UTC+2) is 00:30 UTC
    assert fold_slot.intended_utc_instant == datetime(2027, 10, 31, 0, 30, tzinfo=timezone.utc)
    assert fold_slot.local_offset_minutes == 120


def test_activation_epoch_boundary_no_historical_backfill():
    """T09: Startup before or at activation epoch produces zero due slots."""
    calc = CalendarCalculator("Europe/Berlin")

    epoch = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    definition = ScheduleDefinition(
        deployment_id="test_dep",
        schedule_id="daily_search",
        enabled=True,
        target_times=["07:00"],
        activation_epoch=epoch,
    )

    # Check at epoch + 1 hour (13:00 UTC, 14:00 Berlin). 07:00 for today was before epoch!
    due, newly_recorded = calc.evaluate_due_occurrences(
        definition=definition,
        existing_occurrences=[],
        as_of_utc=datetime(2026, 11, 1, 13, 0, tzinfo=timezone.utc),
    )
    assert due is None
    assert newly_recorded == []


def test_missed_slots_coalesced_and_expired():
    """T09: After 5 days offline, ancient slots expire and recent missed slots coalesce to 1 latest slot."""
    calc = CalendarCalculator("Europe/Berlin")

    epoch = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    definition = ScheduleDefinition(
        deployment_id="test_dep",
        schedule_id="daily_search",
        enabled=True,
        target_times=["07:00"],
        activation_epoch=epoch,
        max_lateness_hours=24,
    )

    # Evaluate on 2026-10-25 at 18:00 UTC (machine offline since Oct 20)
    as_of = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)

    due, newly_recorded = calc.evaluate_due_occurrences(
        definition=definition,
        existing_occurrences=[],
        as_of_utc=as_of,
    )

    assert due is not None
    # Latest eligible slot is 2026-10-25T07:00
    assert due.intended_slot == "2026-10-25T07:00:00 Europe/Berlin"
    assert due.outcome == OccurrenceOutcome.DUE

    # Check newly recorded non-eligible occurrences:
    # 2026-10-20 to 2026-10-24: older than 24h lateness window -> EXPIRED
    expired = [o for o in newly_recorded if o.outcome == OccurrenceOutcome.EXPIRED]
    assert len(expired) >= 4

    # Any un-expired slots before the latest within 24h are COALESCED
    coalesced = [o for o in newly_recorded if o.outcome == OccurrenceOutcome.COALESCED]
    # In daily cadence, only 1 slot falls within 24h of 18:00 UTC, so it became the DUE slot.


def test_multiple_slots_in_lateness_window_coalesced():
    """T09: With frequent cadence (e.g. hourly or 5-min), all missed within lateness window coalesce to latest."""
    calc = CalendarCalculator("Europe/Berlin")

    epoch = datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc)
    definition = ScheduleDefinition(
        deployment_id="test_dep",
        schedule_id="hourly_check",
        enabled=True,
        target_times=["09:00", "10:00", "11:00", "12:00"],
        activation_epoch=epoch,
        max_lateness_hours=24,
    )

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)

    due, newly_recorded = calc.evaluate_due_occurrences(
        definition=definition,
        existing_occurrences=[],
        as_of_utc=as_of,
    )

    assert due is not None
    assert due.intended_slot == "2026-10-31T12:00:00 Europe/Berlin"
    assert due.outcome == OccurrenceOutcome.DUE

    # 09:00, 10:00, 11:00 should be coalesced into 12:00
    coalesced = [o for o in newly_recorded if o.outcome == OccurrenceOutcome.COALESCED]
    assert len(coalesced) == 3
    coalesced_slots = [c.intended_slot for c in coalesced]
    assert "2026-10-31T09:00:00 Europe/Berlin" in coalesced_slots
    assert "2026-10-31T10:00:00 Europe/Berlin" in coalesced_slots
    assert "2026-10-31T11:00:00 Europe/Berlin" in coalesced_slots


def test_already_recorded_slots_are_skipped():
    """T07: Duplicate wake or re-evaluation does not regenerate existing slot records."""
    calc = CalendarCalculator("Europe/Berlin")

    epoch = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
    definition = ScheduleDefinition(
        deployment_id="test_dep",
        schedule_id="daily_search",
        enabled=True,
        target_times=["07:00"],
        activation_epoch=epoch,
    )

    existing = [
        ScheduleOccurrence(
            occurrence_id=uuid.uuid4(),
            deployment_id="test_dep",
            schedule_id="daily_search",
            definition_version=1,
            work_kind=ScheduleKind.SEARCH,
            intended_slot="2026-10-31T07:00:00 Europe/Berlin",
            intended_utc_instant=datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc),
            local_offset_minutes=60,
            outcome=OccurrenceOutcome.SUCCEEDED,
        )
    ]

    due, newly_recorded = calc.evaluate_due_occurrences(
        definition=definition,
        existing_occurrences=existing,
        as_of_utc=datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc),
    )
    assert due is None
    assert newly_recorded == []

