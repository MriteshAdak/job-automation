"""Checked single-page adapter execution and C05 drafting (INGEST-01-S03).

Executes an adapter's fetch_page and draft_posting methods, validates
source and record boundaries, and reconciles issues without dropping
valid neighbor records.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting
from job_automation.sources.models import EffectiveSource

logger = logging.getLogger(__name__)


@dataclass
class PageExecutionResult:
    """Consolidated results of a single executed page."""

    page: AdapterPage
    draft_results: list[DraftResult]
    all_issues: list[RecordIssue]
    raw_records: list[RawPosting]
    observed_posting_ids: list[str]
    parent_refs: list[str]


class PageExecutor:
    """Executes a single page fetch and draft mapping against an Adapter."""

    def __init__(self, effective_source: EffectiveSource, adapter: Adapter) -> None:
        self.effective_source = effective_source
        self.adapter = adapter
        self.config = effective_source.config

    def execute_page(self, continuation: Continuation | None = None) -> PageExecutionResult:
        """Fetch one page, validate its records, draft each record, and reconcile issues."""
        try:
            page = self.adapter.fetch_page(self.config, continuation=continuation)
        except Exception as exc:
            # Wrap unexpected adapter exceptions safely
            logger.exception("Unexpected exception in adapter.fetch_page for '%s'", self.config.source_key)
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Adapter fetch_page raised unexpected error: {type(exc).__name__}: {exc}",
                details={"code": "adapter_exception", "source_key": self.config.source_key},
            )
            page = AdapterPage(
                items=[],
                issues=[],
                raw_response_refs=[],
                continuation_in=continuation,
                continuation_out=None,
                exhausted=False,
                page_error=err,
            )

        valid_raw_records: list[RawPosting] = []
        observed_posting_ids: list[str] = []
        draft_results: list[DraftResult] = []
        page_issues: list[RecordIssue] = list(page.issues)

        # Validate source ownership on each returned item
        for idx, item in enumerate(page.items, start=1):
            if (
                item.source_key.provider != self.config.provider
                or item.source_key.board_id != self.config.board_id
            ):
                issue = RecordIssue(
                    input_ref=item.raw_payload_ref,
                    input_hash=item.raw_content_hash,
                    record_index=idx,
                    source_key=item.source_key,
                    code="foreign_source_key_mismatch",
                    severity="error",
                    message=(
                        f"Item has mismatched source identity ({item.source_key.provider}, "
                        f"{item.source_key.board_id}) expected ({self.config.provider}, {self.config.board_id})"
                    ),
                    category=ErrorCategory.VALIDATION,
                )
                page_issues.append(issue)
                continue

            valid_raw_records.append(item)
            observed_posting_ids.append(item.source_key.source_posting_id)

            # Call draft_posting for each valid record, isolating individual mapping errors
            try:
                draft_res = self.adapter.draft_posting(item)
            except Exception as exc:
                logger.warning(
                    "Unexpected drafting exception for item '%s': %s",
                    item.source_key.source_posting_id,
                    exc,
                )
                issue = RecordIssue(
                    input_ref=item.raw_payload_ref,
                    input_hash=item.raw_content_hash,
                    record_index=idx,
                    source_key=item.source_key,
                    code="draft_mapping_exception",
                    severity="error",
                    message=f"draft_posting raised {type(exc).__name__}: {exc}",
                    category=ErrorCategory.VALIDATION,
                )
                draft_res = DraftResult(
                    raw_reference=item.raw_payload_ref,
                    draft=None,
                    issues=[issue],
                )

            draft_results.append(draft_res)
            page_issues.extend(draft_res.issues)

        # Deduplicate and reconcile issues
        reconciled_issues = self._reconcile_issues(page_issues)

        return PageExecutionResult(
            page=page,
            draft_results=draft_results,
            all_issues=reconciled_issues,
            raw_records=valid_raw_records,
            observed_posting_ids=observed_posting_ids,
            parent_refs=list(page.raw_response_refs),
        )

    def _reconcile_issues(self, issues: Sequence[RecordIssue]) -> list[RecordIssue]:
        seen: set[tuple[str, int | None, str, str]] = set()
        deduped: list[RecordIssue] = []
        for issue in issues:
            key = (issue.input_ref, issue.record_index, issue.code, issue.field_path)
            if key not in seen:
                seen.add(key)
                deduped.append(issue)
        return deduped
