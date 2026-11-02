"""Source mapping conventions and helpers (SOURCE-02-S03).

Extracts source structure into candidate fields without normalization:
- Preserves raw values, HTML/text, location strings, compensation text, and dates.
- Documents the candidate field vocabulary for downstream INGEST-02 normalizer.
- Returns warnings for missing title/company and errors for missing required fields.
- Deep-copies nested structures to prevent caller mutation.
"""

from __future__ import annotations

import copy
from typing import Any

from job_automation.contracts.adapter_results import RecordIssue
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.primitives import SourceKey

# Standard vocabulary for candidate fields in source_mapped_fields
STANDARD_MAPPED_FIELDS = {
    "title",
    "company_name_hint",
    "description",
    "source_url",
    "application_url",
    "locations_raw",
    "workplace_type_raw",
    "employment_type_raw",
    "compensation_raw",
    "source_published_raw",
    "source_deadline_raw",
}


def map_raw_record_to_draft_fields(
    raw_data: dict[str, Any],
    input_ref: str,
    input_hash: str,
    record_index: int | None = None,
    source_key: SourceKey | None = None,
) -> tuple[dict[str, Any], list[RecordIssue]]:
    """Extract candidate fields from a parsed raw record dictionary.

    Returns:
        (source_mapped_fields, issues)
    """
    issues: list[RecordIssue] = []
    mapped: dict[str, Any] = {}
    provenance: dict[str, str] = {}

    # 1. source_url (required for draft)
    source_url = raw_data.get("source_url")
    if not source_url or not str(source_url).strip():
        issues.append(
            RecordIssue(
                input_ref=input_ref,
                input_hash=input_hash,
                record_index=record_index,
                source_key=source_key,
                field_path="source_url",
                code="missing_source_url",
                severity="error",
                message="Record is missing required source_url",
                category=ErrorCategory.VALIDATION,
            )
        )
    else:
        mapped["source_url"] = str(source_url).strip()
        provenance["source_url"] = "source_url"

    # 2. description / text (required for draft)
    # Check 'text' or 'description'
    desc = raw_data.get("text")
    desc_key = "text"
    if desc is None:
        desc = raw_data.get("description")
        desc_key = "description"

    if desc is None or not str(desc).strip():
        issues.append(
            RecordIssue(
                input_ref=input_ref,
                input_hash=input_hash,
                record_index=record_index,
                source_key=source_key,
                field_path="text",
                code="missing_posting_text",
                severity="error",
                message="Record is missing required job posting text/description",
                category=ErrorCategory.VALIDATION,
            )
        )
    else:
        mapped["description"] = str(desc)  # Preserves raw text/HTML without modification
        provenance["description"] = desc_key

    # 3. title (optional in C05, generates warning if missing)
    title = raw_data.get("title")
    if title is not None and str(title).strip():
        mapped["title"] = str(title).strip()
        provenance["title"] = "title"
    else:
        mapped["title"] = None
        issues.append(
            RecordIssue(
                input_ref=input_ref,
                input_hash=input_hash,
                record_index=record_index,
                source_key=source_key,
                field_path="title",
                code="missing_title",
                severity="warning",
                message="Job title was not provided; mapped as null for downstream normalization",
                category=ErrorCategory.VALIDATION,
            )
        )

    # 4. company / company_name_hint (optional)
    company = raw_data.get("company")
    comp_key = "company"
    if company is None:
        company = raw_data.get("company_name_hint")
        comp_key = "company_name_hint"

    if company is not None and str(company).strip():
        mapped["company_name_hint"] = str(company).strip()
        provenance["company_name_hint"] = comp_key
    else:
        mapped["company_name_hint"] = None

    # 5. application_url (optional)
    app_url = raw_data.get("application_url")
    if app_url is not None and str(app_url).strip():
        mapped["application_url"] = str(app_url).strip()
        provenance["application_url"] = "application_url"
    else:
        mapped["application_url"] = None

    # 6. Optional structural fields (preserved as raw strings/collections without normalization)
    for field_name in [
        "locations_raw",
        "workplace_type_raw",
        "employment_type_raw",
        "compensation_raw",
        "source_published_raw",
        "source_deadline_raw",
    ]:
        val = raw_data.get(field_name)
        if val is not None and str(val).strip():
            mapped[field_name] = copy.deepcopy(val)
            provenance[field_name] = field_name
        else:
            mapped[field_name] = None

    mapped["mapping_version"] = "1.0"
    mapped["provenance"] = provenance

    return mapped, issues

