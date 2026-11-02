"""Import reporting and diagnostic error isolation (SOURCE-02-S06).

Aggregates page results, isolates record-level errors, computes consistent counters,
and produces human-readable diagnostic summaries without leaking credentials or raw texts.
"""

from __future__ import annotations

from typing import Any
from pydantic import Field

from job_automation.contracts.adapter_results import AdapterPage, DraftResult, RecordIssue
from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError


class ImportReport(ContractModel):
    """Safe, structured report summarizing the results of a manual import."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    status: str = Field(
        description="Overall import status: 'accepted', 'partial', or 'failed'"
    )
    scan_complete: bool = Field(
        description="True if the input was scanned to completion without fatal interruption"
    )
    records_encountered: int = Field(ge=0, description="Total logical data records encountered")
    records_accepted: int = Field(ge=0, description="Total valid raw records drafted")
    records_rejected: int = Field(ge=0, description="Total records rejected due to blocking errors")
    records_with_warnings: int = Field(ge=0, description="Total records with non-blocking warnings")
    total_issues: int = Field(ge=0, description="Total issue count across all records")
    unread_remainder: int | None = Field(
        default=None, description="Known unread records count if scan was interrupted"
    )
    issues: list[RecordIssue] = Field(
        default_factory=list, description="Ordered list of record issues"
    )
    guidance: list[str] = Field(
        default_factory=list, description="Safe correction guidance for rejected records"
    )
    page_error: ClassifiedError | None = Field(
        default=None, description="Page-level or file-level fatal error if any"
    )


def build_import_report(
    pages: list[AdapterPage],
    draft_results: list[DraftResult] | None = None,
    scan_complete: bool = True,
    unread_remainder: int | None = None,
    page_error: ClassifiedError | None = None,
) -> ImportReport:
    """Build an ImportReport from a list of collected AdapterPages and DraftResults."""
    drafts = draft_results or []
    all_issues: list[RecordIssue] = []
    total_accepted = 0

    # Collect issues and counts from pages
    for page in pages:
        total_accepted += len(page.items)
        all_issues.extend(page.issues)
        if page.page_error is not None and page_error is None:
            page_error = page.page_error

    # Group issues by record_index to compute unique rejected vs warning records
    record_issues: dict[int | None, list[RecordIssue]] = {}
    for issue in all_issues:
        idx = issue.record_index
        record_issues.setdefault(idx, []).append(issue)

    rejected_records = 0
    warning_records = 0
    guidance_items: list[str] = []

    for idx, issues in sorted(record_issues.items(), key=lambda kv: (kv[0] is None, kv[0])):
        has_error = any(iss.severity == "error" for iss in issues)
        has_warning = any(iss.severity == "warning" for iss in issues)

        loc = f"Record {idx}" if idx is not None else "Input"
        if has_error:
            rejected_records += 1
            error_codes = [iss.code for iss in issues if iss.severity == "error"]
            guidance_items.append(
                f"{loc}: rejected due to {', '.join(error_codes)}. Check required fields (source_url, text) and format."
            )
        elif has_warning:
            warning_records += 1

    records_encountered = total_accepted + rejected_records
    total_issues = len(all_issues)

    # Determine status
    if page_error is not None:
        if total_accepted > 0:
            status = "partial"
        else:
            status = "failed"
    elif rejected_records > 0:
        if total_accepted > 0:
            status = "partial"
        else:
            status = "failed"
    else:
        status = "accepted"

    return ImportReport(
        status=status,
        scan_complete=scan_complete and (page_error is None),
        records_encountered=records_encountered,
        records_accepted=total_accepted,
        records_rejected=rejected_records,
        records_with_warnings=warning_records,
        total_issues=total_issues,
        unread_remainder=unread_remainder,
        issues=all_issues,
        guidance=guidance_items,
        page_error=page_error,
    )

