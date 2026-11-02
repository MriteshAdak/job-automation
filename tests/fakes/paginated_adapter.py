"""Deterministic scripted paginated adapter for test conformance verification (SOURCE-02-S07).

Kept strictly in test code. Used to prove that fake multi-page traversal and manual imports
satisfy the identical Adapter protocol without live provider networks.
"""

from __future__ import annotations

from typing import Any

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.sources import SourceConfig


class ScriptedPaginatedFakeAdapter(Adapter):
    """Test fake implementing Adapter with deterministic scripted pages."""

    def __init__(
        self,
        pages: dict[str | None, AdapterPage] | None = None,
        drafts: dict[str, DraftResult] | None = None,
        expected_source_key: str | None = None,
    ) -> None:
        self.pages = pages or {}
        self.drafts = drafts or {}
        self.expected_source_key = expected_source_key
        self.fetch_calls: list[tuple[SourceConfig, Continuation | None]] = []
        self.draft_calls: list[RawPosting] = []

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        """Fetch a scripted page corresponding to the continuation token value."""
        self.fetch_calls.append((config, continuation))

        if self.expected_source_key and config.source_key != self.expected_source_key:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Expected source key '{self.expected_source_key}', got '{config.source_key}'",
                details={"code": "source_key_mismatch"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        token_value = continuation.value if continuation is not None else None

        if token_value not in self.pages:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Scripted adapter has no page for token '{token_value}'",
                details={"code": "unknown_continuation_token"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        # Return a copy of the scripted page to prevent caller mutation of fake state
        page = self.pages[token_value]
        return page.model_copy(deep=True)

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        """Map a raw posting into a scripted DraftResult."""
        self.draft_calls.append(raw)
        if raw.raw_payload_ref in self.drafts:
            return self.drafts[raw.raw_payload_ref].model_copy(deep=True)

        # Default fallback mapping
        draft = SourceJobDraft(
            raw_reference=raw.raw_payload_ref,
            source_key=raw.source_key,
            fetch_time=raw.fetch_time,
            original_fields={"raw": raw.raw_payload},
            source_mapped_fields={
                "title": "Scripted Job",
                "company_name_hint": "Scripted Corp",
                "description": raw.raw_payload,
                "source_url": f"https://example.invalid/jobs/{raw.source_key.source_posting_id}",
            },
        )
        return DraftResult(raw_reference=raw.raw_payload_ref, draft=draft, issues=[])
