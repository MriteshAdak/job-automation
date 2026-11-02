"""Posting availability tracking package (IDENTITY-02).

Consumes C04 FetchManifest contracts and IDENTITY-01 source identity mappings
to maintain per-scope source posting availability and aggregate C07 canonical
availability without mutating candidate application status, decisions, or notes.
"""

from __future__ import annotations

from job_automation.identity.availability.aggregate import (
    aggregate_canonical_availability,
    aggregate_observation_timestamps,
)
from job_automation.identity.availability.errors import (
    AvailabilityConfigurationError,
    AvailabilityConflictError,
    AvailabilityError,
    AvailabilityLedgerError,
    AvailabilityScopeError,
)
from job_automation.identity.availability.evidence import (
    compute_manifest_fingerprint,
    is_manifest_eligible_for_negative_inference,
)
from job_automation.identity.availability.inspection import CanonicalAvailabilitySummary
from job_automation.identity.availability.models import (
    AvailabilityDecision,
    AvailabilityProcessResult,
    CanonicalChangeResult,
    SourceChangeResult,
    SourcePostingAvailability,
)
from job_automation.identity.availability.rules import evaluate_miss, evaluate_sighting
from job_automation.identity.availability.service import AvailabilityService
from job_automation.identity.availability.settings import (
    AvailabilityPolicy,
    AvailabilityRuleSettings,
    load_availability_policy,
)

__all__ = [
    "AvailabilityConfigurationError",
    "AvailabilityConflictError",
    "AvailabilityDecision",
    "AvailabilityError",
    "AvailabilityLedgerError",
    "AvailabilityPolicy",
    "AvailabilityProcessResult",
    "AvailabilityRuleSettings",
    "AvailabilityScopeError",
    "AvailabilityService",
    "CanonicalAvailabilitySummary",
    "CanonicalChangeResult",
    "SourceChangeResult",
    "SourcePostingAvailability",
    "aggregate_canonical_availability",
    "aggregate_observation_timestamps",
    "compute_manifest_fingerprint",
    "evaluate_miss",
    "evaluate_sighting",
    "is_manifest_eligible_for_negative_inference",
    "load_availability_policy",
]

