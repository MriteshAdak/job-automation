"""Configuration and policy settings for posting availability tracking (IDENTITY-02-S01).

Enforces:
- Integer miss thresholds >= 2 (rejects booleans and thresholds < 2).
- Non-negative finite grace periods in seconds (48 hours = 172800.0s default).
- Precedence: scope_overrides > source_overrides > default_rules.
- Deterministic SHA-256 policy fingerprint over canonical JSON representation.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from job_automation.contracts.base import ContractModel
from job_automation.identity.availability.errors import AvailabilityConfigurationError


class AvailabilityRuleSettings(ContractModel):
    """Configurable threshold and grace parameters for a specific scope or source."""

    consecutive_complete_misses: int = Field(
        default=3,
        description="Number of consecutive complete inventory misses required for closure (must be >= 2)",
    )
    grace_seconds: float = Field(
        default=172800.0,
        description="Minimum elapsed time in seconds from first miss before closure can occur (48h default)",
    )

    @field_validator("consecutive_complete_misses", mode="before")
    @classmethod
    def _validate_misses(cls, v: Any) -> int:
        if isinstance(v, bool):
            raise AvailabilityConfigurationError(
                "consecutive_complete_misses cannot be a boolean value"
            )
        try:
            val = int(v)
        except (ValueError, TypeError) as err:
            raise AvailabilityConfigurationError(
                f"consecutive_complete_misses must be an integer, got {v!r}"
            ) from err
        if val < 2:
            raise AvailabilityConfigurationError(
                f"consecutive_complete_misses must be at least 2, got {val}"
            )
        return val

    @field_validator("grace_seconds", mode="before")
    @classmethod
    def _validate_grace(cls, v: Any) -> float:
        if isinstance(v, bool):
            raise AvailabilityConfigurationError("grace_seconds cannot be a boolean value")
        try:
            val = float(v)
        except (ValueError, TypeError) as err:
            raise AvailabilityConfigurationError(
                f"grace_seconds must be a float, got {v!r}"
            ) from err
        if math.isnan(val) or math.isinf(val) or val < 0.0:
            raise AvailabilityConfigurationError(
                f"grace_seconds must be a finite non-negative number, got {val}"
            )
        return val


class AvailabilityPolicy(ContractModel):
    """Complete versioned availability policy with global defaults and overrides."""

    schema_version: str = Field(
        default="1.0",
        description="Schema version of availability policy configuration",
    )
    policy_version: str = Field(
        default="1.0",
        description="Policy version identifier",
    )
    default_rules: AvailabilityRuleSettings = Field(
        default_factory=AvailabilityRuleSettings,
        description="Default rules applied when no specific override matches",
    )
    source_overrides: dict[str, AvailabilityRuleSettings] = Field(
        default_factory=dict,
        description="Overrides keyed by source_key",
    )
    scope_overrides: dict[str, AvailabilityRuleSettings] = Field(
        default_factory=dict,
        description="Overrides keyed by scope_id",
    )

    @property
    def fingerprint(self) -> str:
        """Deterministic SHA-256 digest of canonical policy representation."""
        raw = self.model_dump(mode="json")
        canonical_bytes = json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical_bytes).hexdigest()
        return f"sha256:{digest}"

    def get_effective_rules(self, source_key: str, scope_id: str) -> AvailabilityRuleSettings:
        """Resolve effective rule settings following precedence: scope > source > default."""
        if scope_id in self.scope_overrides:
            return self.scope_overrides[scope_id]
        if source_key in self.source_overrides:
            return self.source_overrides[source_key]
        return self.default_rules


def load_availability_policy(
    policy_ref: str | Path | dict[str, Any] | None = None,
) -> AvailabilityPolicy:
    """Load and validate an AvailabilityPolicy from a file path, dict, or defaults."""
    if policy_ref is None:
        return AvailabilityPolicy()

    if isinstance(policy_ref, dict):
        return AvailabilityPolicy.model_validate(policy_ref)

    p = Path(policy_ref).resolve()
    if not p.is_file():
        raise AvailabilityConfigurationError(f"Availability policy file not found: {p}")

    try:
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        return AvailabilityPolicy.model_validate(data)
    except json.JSONDecodeError as err:
        raise AvailabilityConfigurationError(
            f"Malformed JSON in availability policy: {err}"
        ) from err
    except Exception as err:
        raise AvailabilityConfigurationError(
            f"Failed to load availability policy from {p}: {err}"
        ) from err

