"""Source date normalization and observation semantics (INGEST-02).

Normalizes source dates into UTC instants without inventing precision:
- Converts offset-aware ISO strings to UTC instants.
- Accepts declared numeric epoch units only (never guesses by digit count).
- Rejects booleans as numeric timestamps.
- Preserves date-only/month-only precision as unknown timestamps with warnings
  (never invents midnight or end-of-day).
- Treats naive timestamps as ambiguous unless an explicit timezone is declared.
- Handles DST folds and gaps safely via ZoneInfo.
- Retains draft fetch_time as immutable UTC observed_at (never uses wall clock).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from job_automation.contracts.errors import ValidationIssue

DATE_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_ONLY_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def normalize_source_date(
    raw_date: Any,
    field_name: str = "source_published_at",
    declared_unit: str | None = None,
    declared_event: str | None = None,
    declared_tz: str | None = None,
) -> tuple[datetime | None, list[ValidationIssue]]:
    """Normalize a source date into a UTC datetime instant or structured issue.

    Returns:
        (utc_datetime, issues)
    """
    if raw_date is None:
        return None, []

    # Explicitly reject booleans (bool is a subclass of int in Python)
    if isinstance(raw_date, bool):
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="invalid_field_type",
                message=f"Date field '{field_name}' must not be a boolean",
                severity="error",
            )
        ]

    # Numeric timestamp (int or float)
    if isinstance(raw_date, (int, float)):
        if declared_unit is None:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="ambiguous_value",
                    message=(
                        f"Numeric timestamp in '{field_name}' lacks declared unit/event metadata; "
                        "will not guess from digit count"
                    ),
                    severity="warning",
                )
            ]

        try:
            val = float(raw_date)
            if declared_unit.lower() in ("s", "sec", "second", "seconds"):
                dt = datetime.fromtimestamp(val, tz=timezone.utc)
            elif declared_unit.lower() in ("ms", "milli", "millisecond", "milliseconds"):
                dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
            else:
                return None, [
                    ValidationIssue(
                        field_path=field_name,
                        code="unsupported_representation",
                        message=f"Unsupported timestamp unit '{declared_unit}' for '{field_name}'",
                        severity="warning",
                    )
                ]
            return dt, []
        except (OSError, OverflowError, ValueError):
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="invalid_value",
                    message=f"Numeric timestamp in '{field_name}' is out of valid range",
                    severity="error",
                )
            ]

    # String format
    if not isinstance(raw_date, str):
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="invalid_field_type",
                message=f"Date field '{field_name}' must be a string or number, got {type(raw_date).__name__}",
                severity="error",
            )
        ]

    val_str = raw_date.strip()
    if not val_str:
        return None, []

    # Date-only (YYYY-MM-DD) or Month-only (YYYY-MM)
    if DATE_ONLY_PATTERN.match(val_str) or MONTH_ONLY_PATTERN.match(val_str):
        # Do not invent midnight or end-of-day; keep timestamp null and warn
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="unsupported_representation",
                message=(
                    f"Date-only precision '{val_str}' in '{field_name}' cannot be converted "
                    "to a timestamp instant without fabricating precision"
                ),
                severity="warning",
            )
        ]

    # ISO-8601 string parsing
    iso_clean = val_str.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_clean)
    except ValueError:
        return None, [
            ValidationIssue(
                field_path=field_name,
                code="invalid_value",
                message=f"String in '{field_name}' cannot be parsed as a valid ISO datetime",
                severity="error",
            )
        ]

    # Timezone awareness check
    if parsed.tzinfo is not None:
        # Offset-aware: convert instant to UTC
        return parsed.astimezone(timezone.utc), []

    # Naive datetime
    if declared_tz:
        try:
            tz = ZoneInfo(declared_tz)
        except Exception:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="invalid_value",
                    message=f"Unknown declared timezone '{declared_tz}' for '{field_name}'",
                    severity="error",
                )
            ]

        # Check for nonexistent time (spring DST gap)
        localized = parsed.replace(tzinfo=tz)
        roundtrip = localized.astimezone(timezone.utc).astimezone(tz)
        if roundtrip.hour != parsed.hour or roundtrip.minute != parsed.minute:
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="invalid_value",
                    message=f"Naive time '{val_str}' is nonexistent in timezone '{declared_tz}' (DST gap)",
                    severity="error",
                )
            ]

        # Check for ambiguous time (autumn DST fold)
        fold0 = parsed.replace(tzinfo=tz, fold=0)
        fold1 = parsed.replace(tzinfo=tz, fold=1)
        if fold0.utcoffset() != fold1.utcoffset():
            return None, [
                ValidationIssue(
                    field_path=field_name,
                    code="ambiguous_value",
                    message=f"Naive time '{val_str}' is ambiguous in timezone '{declared_tz}' (DST fold)",
                    severity="warning",
                )
            ]

        return localized.astimezone(timezone.utc), []

    # Naive timestamp without declared timezone
    return None, [
        ValidationIssue(
            field_path=field_name,
            code="ambiguous_value",
            message=f"Naive timestamp '{val_str}' in '{field_name}' lacks timezone information",
            severity="warning",
        )
    ]


def normalize_observed_at(fetch_time: Any) -> tuple[datetime, list[ValidationIssue]]:
    """Convert draft fetch_time to UTC observed_at instant.

    Never invents or uses wall clock time.
    """
    if isinstance(fetch_time, datetime):
        if fetch_time.tzinfo is None:
            # Assume UTC if naive
            return fetch_time.replace(tzinfo=timezone.utc), []
        return fetch_time.astimezone(timezone.utc), []

    if isinstance(fetch_time, str):
        dt, issues = normalize_source_date(fetch_time, field_name="observed_at")
        if dt is not None:
            return dt, issues

    # Fallback to epoch if somehow invalid or missing
    return datetime.fromtimestamp(0, tz=timezone.utc), [
        ValidationIssue(
            field_path="observed_at",
            code="invalid_value",
            message="Invalid fetch_time on source draft; cannot resolve observation instant",
            severity="error",
        )
    ]

