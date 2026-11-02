"""Source adapter interfaces, binding, and manual import adapters (SOURCE-02).

SOURCE-03-arbeitnow: ArbeitnowAdapter added.
"""

from __future__ import annotations

from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.adapters.binding import (
    validate_adapter_binding,
    verify_runtime_config,
)
from job_automation.sources.adapters.continuation import (
    create_continuation,
    validate_continuation,
)
from job_automation.sources.adapters.import_report import (
    ImportReport,
    build_import_report,
)
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
from job_automation.sources.adapters.manual_identity import (
    derive_manual_posting_id,
    validate_http_url,
)
from job_automation.sources.adapters.manual_text import ManualTextAdapter
from job_automation.sources.adapters.mapping import (
    STANDARD_MAPPED_FIELDS,
    map_raw_record_to_draft_fields,
)
from job_automation.sources.adapters.raw import (
    InMemoryRawCaptureSink,
    RawCaptureSink,
    compute_content_hash,
    verify_content_hash,
)

__all__ = [
    "ArbeitnowAdapter",
    "ImportReport",
    "InMemoryRawCaptureSink",
    "ManualCsvAdapter",
    "ManualTextAdapter",
    "RawCaptureSink",
    "STANDARD_MAPPED_FIELDS",
    "build_import_report",
    "compute_content_hash",
    "create_continuation",
    "derive_manual_posting_id",
    "map_raw_record_to_draft_fields",
    "validate_adapter_binding",
    "validate_continuation",
    "validate_http_url",
    "verify_content_hash",
    "verify_runtime_config",
]

