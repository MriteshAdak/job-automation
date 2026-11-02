"""Adapter boundary result contracts and auxiliary models (SOURCE-02).

Defines typed representations for:
- Continuation: traversal state and token binding
- RecordIssue: record-level issues and warnings
- AdapterPage: page of raw postings and page-level metadata
- DraftResult: drafted job structure or blocking errors
"""

from __future__ import annotations

import base64
import json
from typing import Any
from pydantic import Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import ContentHash, SourceKey


class Continuation(ContractModel):
    """Opaque pagination or resumption token bound to source and scope."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    kind: str = Field(
        description="Continuation kind: cursor, page, offset, or local_record"
    )
    value: str = Field(
        description="Opaque continuation value (string-encoded for persistence)"
    )
    source_key: str = Field(description="Configuration source key")
    scope_id: str = Field(description="Deterministic scope identifier")
    adapter_name: str = Field(description="Adapter identifier or version binding")
    input_hash: str | None = Field(
        default=None, description="SHA-256 hash of input bytes for manual sources"
    )
    options_hash: str | None = Field(
        default=None, description="Hash of parsing/paging options for manual sources"
    )

    def encode(self) -> str:
        """Deterministic reversible string serialization for C04 cursor storage."""
        data = self.model_dump(mode="json")
        json_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        b64 = base64.urlsafe_b64encode(json_bytes).decode("ascii").rstrip("=")
        return f"cont-v1:{b64}"

    @classmethod
    def decode(cls, token: str) -> Continuation:
        """Decode a serialized continuation string back into a Continuation instance."""
        if not token.startswith("cont-v1:"):
            raise ValueError(f"Unsupported continuation token prefix: {token[:16]}")
        raw_b64 = token[len("cont-v1:"):]
        # Add back required base64 padding
        padding = (4 - len(raw_b64) % 4) % 4
        raw_b64 += "=" * padding
        try:
            json_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
            data = json.loads(json_bytes.decode("utf-8"))
            return cls.model_validate(data)
        except Exception as exc:
            raise ValueError(f"Malformed continuation token: {exc}") from exc


class RecordIssue(ContractModel):
    """Record-level validation or mapping issue with exact input locator."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    input_ref: str = Field(description="Reference or URI of the input source")
    input_hash: str = Field(description="Content hash of the input")
    record_index: int | None = Field(
        default=None, ge=1, description="1-based logical record index within input"
    )
    line_start: int | None = Field(
        default=None, ge=1, description="1-based physical start line"
    )
    line_end: int | None = Field(
        default=None, ge=1, description="1-based physical end line"
    )
    source_key: SourceKey | None = Field(
        default=None, description="Scoped source identity if established"
    )
    field_path: str = Field(
        default="", description="Field path within record associated with issue"
    )
    code: str = Field(description="Stable programmatic issue code")
    severity: str = Field(
        default="error", description="Issue severity: 'error' (blocking) or 'warning'"
    )
    message: str = Field(description="Safe human-readable issue description")
    category: ErrorCategory = Field(
        default=ErrorCategory.VALIDATION, description="Classified error category"
    )

    @model_validator(mode="after")
    def validate_severity(self) -> RecordIssue:
        if self.severity not in {"error", "warning"}:
            raise ValueError(f"Invalid severity '{self.severity}'; must be 'error' or 'warning'")
        return self


class AdapterPage(ContractModel):
    """Page of raw postings produced by an Adapter."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    items: list[RawPosting] = Field(
        default_factory=list, description="Ordered C05 raw records on this page"
    )
    issues: list[RecordIssue] = Field(
        default_factory=list, description="Ordered record issues encountered on this page"
    )
    raw_response_refs: list[str] = Field(
        default_factory=list, description="References to captured raw response payloads"
    )
    continuation_in: Continuation | None = Field(
        default=None, description="Continuation token used to fetch this page"
    )
    continuation_out: Continuation | None = Field(
        default=None, description="Continuation token to fetch the next page"
    )
    exhausted: bool = Field(
        default=False, description="True if no more records are available from this source"
    )
    truncated: bool = Field(
        default=False, description="True if page was cut short by a budget or limit"
    )
    truncation_reason: str | None = Field(
        default=None, description="Explanation if truncated"
    )
    page_error: ClassifiedError | None = Field(
        default=None, description="Classified error if page-level fetch failed"
    )
    record_count: int = Field(
        default=0, ge=0, description="Number of raw records on this page"
    )
    issue_count: int = Field(
        default=0, ge=0, description="Number of record issues on this page"
    )

    @model_validator(mode="before")
    @classmethod
    def set_counts_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "record_count" not in data and "items" in data:
                data["record_count"] = len(data["items"])
            if "issue_count" not in data and "issues" in data:
                data["issue_count"] = len(data["issues"])
        return data

    @model_validator(mode="after")
    def validate_page_invariants(self) -> AdapterPage:
        if self.exhausted and self.continuation_out is not None:
            raise ValueError("Contradictory page state: exhausted=True but continuation_out is present")
        if self.record_count != len(self.items):
            raise ValueError(f"record_count ({self.record_count}) does not match len(items) ({len(self.items)})")
        if self.issue_count != len(self.issues):
            raise ValueError(f"issue_count ({self.issue_count}) does not match len(issues) ({len(self.issues)})")
        return self


class DraftResult(ContractModel):
    """Result of mapping a single RawPosting into a SourceJobDraft."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    raw_reference: str = Field(
        min_length=1, description="Reference to the underlying raw posting"
    )
    draft: SourceJobDraft | None = Field(
        default=None, description="Mapped draft if drafting succeeded without blocking errors"
    )
    issues: list[RecordIssue] = Field(
        default_factory=list, description="Warnings or blocking issues encountered during mapping"
    )

    @model_validator(mode="after")
    def validate_draft_issues(self) -> DraftResult:
        has_blocking = any(issue.severity == "error" for issue in self.issues)
        if has_blocking:
            if self.draft is not None:
                raise ValueError("DraftResult cannot contain a draft when blocking error issues exist")
        else:
            if self.draft is None:
                raise ValueError("DraftResult with no blocking error issues must contain a draft")
        if self.draft is not None and self.draft.raw_reference != self.raw_reference:
            raise ValueError(
                f"raw_reference mismatch: DraftResult has '{self.raw_reference}', draft has '{self.draft.raw_reference}'"
            )
        return self

