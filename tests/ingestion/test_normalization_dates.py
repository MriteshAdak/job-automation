"""Tests for source date normalization and observation semantics (INGEST-02-S04)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from job_automation.ingestion.normalization.dates import (
    normalize_observed_at,
    normalize_source_date,
)


def test_normalize_offset_aware_iso_date_to_utc() -> None:
    """Offset-aware ISO dates are converted accurately to UTC instants."""
    raw = "2026-10-28T09:30:00+01:00"
    dt, issues = normalize_source_date(raw, field_name="source_published_at")
    assert dt == datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)
    assert not issues

    raw_z = "2026-10-28T08:30:00Z"
    dt_z, issues_z = normalize_source_date(raw_z, field_name="source_published_at")
    assert dt_z == datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)
    assert not issues_z


def test_normalize_declared_numeric_epoch() -> None:
    """Numeric epoch requires declared unit and never guesses from digit count."""
    # Undeclared unit -> ambiguous_value warning
    dt_ambig, issues_ambig = normalize_source_date(1730035200, field_name="source_published_at")
    assert dt_ambig is None
    assert any(iss.code == "ambiguous_value" for iss in issues_ambig)

    # Declared seconds
    dt_sec, issues_sec = normalize_source_date(
        1730035200,
        field_name="source_published_at",
        declared_unit="seconds",
    )
    assert dt_sec == datetime(2024, 10, 27, 13, 20, 0, tzinfo=timezone.utc)
    assert not issues_sec

    # Epoch 0
    dt_zero, issues_zero = normalize_source_date(0, field_name="source_published_at", declared_unit="seconds")
    assert dt_zero == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert not issues_zero


def test_reject_boolean_as_date() -> None:
    """Booleans are explicitly rejected as invalid date field types."""
    dt_bool, issues_bool = normalize_source_date(True, field_name="source_published_at")
    assert dt_bool is None
    assert any(iss.code == "invalid_field_type" for iss in issues_bool)


def test_date_only_preserves_precision_without_inventing_time() -> None:
    """Date-only (YYYY-MM-DD) values do not invent midnight or end-of-day timestamps."""
    raw = "2026-10-31"
    dt, issues = normalize_source_date(raw, field_name="source_deadline_at")
    assert dt is None
    assert any(iss.code == "unsupported_representation" for iss in issues)


def test_absent_deadline_is_not_invented() -> None:
    """Missing or absent closing deadline stays None without warnings."""
    dt, issues = normalize_source_date(None, field_name="source_deadline_at")
    assert dt is None
    assert not issues


def test_naive_datetime_requires_timezone_declaration() -> None:
    """Naive datetime strings are ambiguous unless a timezone is declared."""
    naive_str = "2026-10-28T09:30:00"
    dt_none, issues_none = normalize_source_date(naive_str, field_name="source_published_at")
    assert dt_none is None
    assert any(iss.code == "ambiguous_value" for iss in issues_none)

    # With declared Berlin timezone
    dt_berlin, issues_berlin = normalize_source_date(
        naive_str,
        field_name="source_published_at",
        declared_tz="Europe/Berlin",
    )
    assert dt_berlin == datetime(2026, 10, 28, 8, 30, 0, tzinfo=timezone.utc)
    assert not issues_berlin


def test_berlin_dst_gap_and_fold() -> None:
    """Europe/Berlin DST transition gap and fold are handled safely."""
    # 2026-03-29 02:30 does not exist in Europe/Berlin (spring forward 02:00 -> 03:00)
    gap_str = "2026-03-29T02:30:00"
    dt_gap, issues_gap = normalize_source_date(
        gap_str,
        field_name="source_published_at",
        declared_tz="Europe/Berlin",
    )
    assert dt_gap is None
    assert any(iss.code == "invalid_value" for iss in issues_gap)

    # 2026-10-25 02:30 is ambiguous in Europe/Berlin (autumn repeat)
    fold_str = "2026-10-25T02:30:00"
    dt_fold, issues_fold = normalize_source_date(
        fold_str,
        field_name="source_published_at",
        declared_tz="Europe/Berlin",
    )
    assert dt_fold is None
    assert any(iss.code == "ambiguous_value" for iss in issues_fold)


def test_observed_at_comes_from_fetch_time() -> None:
    """observed_at preserves draft fetch_time converted to UTC without wall-clock drift."""
    fixed_time = datetime(2026, 10, 28, 11, 45, 0, tzinfo=timezone.utc)
    obs, issues = normalize_observed_at(fixed_time)
    assert obs == fixed_time
    assert not issues

