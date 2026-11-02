"""Source registry and access policy package (SOURCE-01).

Implements source registration, configuration validation, and checked source selection
using the existing C03 SourceConfig contract.
"""

from __future__ import annotations

from job_automation.sources.access import (
    validate_access_review,
    validate_attribution_review,
)
from job_automation.sources.adapters import (
    ImportReport,
    InMemoryRawCaptureSink,
    ManualCsvAdapter,
    ManualTextAdapter,
    RawCaptureSink,
    build_import_report,
)
from job_automation.sources.inventory import compute_scope_id, validate_inventory_scope
from job_automation.sources.loader import load_source_registry
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
    SourceRegistryEnvelope,
    SourceSelectionResult,
)
from job_automation.sources.request_policy import validate_request_policy
from job_automation.sources.service import SourceRegistryService
from job_automation.sources.validation import validate_source_config

__all__ = [
    "AccessReview",
    "AccessReviewStatus",
    "AttributionReview",
    "AttributionStatus",
    "EffectiveRequestPolicy",
    "EffectiveSource",
    "ImportReport",
    "InMemoryRawCaptureSink",
    "InventoryScope",
    "ManualCsvAdapter",
    "ManualTextAdapter",
    "RawCaptureSink",
    "SourceRegistryEnvelope",
    "SourceRegistryService",
    "SourceSelectionResult",
    "build_import_report",
    "compute_scope_id",
    "load_source_registry",
    "validate_access_review",
    "validate_attribution_review",
    "validate_inventory_scope",
    "validate_request_policy",
    "validate_source_config",
]

