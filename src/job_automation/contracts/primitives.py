"""Shared primitive types used across all contracts.

Conventions (blueprint §4):
- UUIDs for locally assigned persistent identities.
- Provider IDs are opaque strings scoped by provider and board.
- UTC ISO-8601 timestamps with timezone offsets for machine events.
- Candidate date-only or month-only facts retain their actual precision.
- null means unknown/not supplied, not false or zero.
- Content hashes identify revisions, not permanent identities.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    Field,
    field_validator,
    AwareDatetime,
)

from job_automation.contracts.base import ContractModel


# ---------------------------------------------------------------------------
# Simple annotated types
# ---------------------------------------------------------------------------

LocalId = Annotated[uuid.UUID, Field(description="Locally assigned UUID identity")]

ProviderId = Annotated[
    str,
    Field(
        min_length=1,
        description="Opaque provider-scoped identifier; preserves leading zeros",
    ),
]

ContentHash = Annotated[
    str,
    Field(
        pattern=r"^sha256:[a-f0-9]{64}$",
        description="SHA-256 content hash prefixed with algorithm",
    ),
]

SchemaVersion = Annotated[
    str,
    Field(
        pattern=r"^\d+\.\d+$",
        description="Schema version in major.minor format",
    ),
]


# ---------------------------------------------------------------------------
# Source key — scoped uniqueness for source postings
# ---------------------------------------------------------------------------


class SourceKey(ContractModel):
    """Unique source posting identity: (provider, board_id, source_posting_id).

    Two postings with the same tuple are the same source posting.
    Different board_ids under the same provider are distinct.
    """

    provider: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    source_posting_id: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# UTC-aware datetime
# ---------------------------------------------------------------------------

UtcDatetime = Annotated[
    AwareDatetime,
    Field(description="UTC datetime with +00:00 offset"),
]


def validate_utc(dt: datetime) -> datetime:
    """Validate that a datetime is UTC (offset zero)."""
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"Datetime must be UTC (+00:00), got offset {dt.utcoffset()}")
    return dt


# ---------------------------------------------------------------------------
# Precision-preserving dates for candidate facts
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"^\d{4}$")
_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class PrecisionDate(ContractModel):
    """Date with explicit precision: day, month, or year.

    Month precision '2021-05' stays as-is; no day is fabricated.
    """

    value: str = Field(description="ISO date string matching the precision")
    precision: Literal["day", "month", "year"]

    @field_validator("value")
    @classmethod
    def _validate_format(cls, v: str, info: object) -> str:
        # info.data may not have 'precision' yet during model_validate,
        # so we validate the format itself and cross-check in model_validator
        return v

    def model_post_init(self, __context: object) -> None:
        """Cross-validate value format against precision."""
        if self.precision == "year" and not _YEAR_RE.match(self.value):
            raise ValueError(f"Year precision requires YYYY, got '{self.value}'")
        if self.precision == "month" and not _MONTH_RE.match(self.value):
            raise ValueError(f"Month precision requires YYYY-MM, got '{self.value}'")
        if self.precision == "day" and not _DAY_RE.match(self.value):
            raise ValueError(f"Day precision requires YYYY-MM-DD, got '{self.value}'")


# ---------------------------------------------------------------------------
# Money with explicit currency and null semantics
# ---------------------------------------------------------------------------


class MoneyAmount(ContractModel):
    """Monetary amount with explicit currency.

    A null amount means unknown, not zero. An explicit zero means zero.
    Currency uses ISO 4217 three-letter codes.
    """

    amount: Decimal = Field(description="Monetary value; null at parent level means unknown")
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code",
    )

