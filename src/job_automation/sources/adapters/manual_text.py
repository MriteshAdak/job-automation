"""Manual URL-plus-text adapter implementation (SOURCE-02-S04).

Allows importing a single job posting by supplying a source URL and local posting text
or a path to a local text file.

Strict invariants:
- Zero automated network calls (no HTTP, DNS, link previews, or redirection).
- Exact preservation of original text/HTML without sanitization or guessing.
- Explicit input_base_path resolution for relative file paths.
- Strict UTF-8/BOM handling and handle closure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from job_automation.contracts.adapter_results import (
    AdapterPage,
    Continuation,
    DraftResult,
    RecordIssue,
)
from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import RawPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.binding import (
    validate_adapter_binding,
    verify_runtime_config,
)
from job_automation.sources.adapters.manual_identity import (
    derive_manual_posting_id,
    validate_http_url,
)
from job_automation.sources.adapters.mapping import map_raw_record_to_draft_fields
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash
from job_automation.sources.models import EffectiveSource


class ManualTextAdapter(Adapter):
    """Adapter for importing a single job posting from a URL and local text."""

    def __init__(
        self,
        effective_source: EffectiveSource,
        capture_sink: RawCaptureSink,
        source_url: str,
        text: str | None = None,
        text_path: Path | str | None = None,
        input_base_path: Path | None = None,
        source_posting_id: str | None = None,
        title: str | None = None,
        company: str | None = None,
        application_url: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        validate_adapter_binding(
            effective_source,
            supported_method=AcquisitionMethod.MANUAL_IMPORT,
            adapter_name="manual_text",
        )
        self.effective_source = effective_source
        self.capture_sink = capture_sink
        self.source_url = source_url
        self.raw_text = text
        self.text_path = text_path
        self.input_base_path = input_base_path
        self.source_posting_id = source_posting_id
        self.title = title
        self.company = company
        self.application_url = application_url
        self.clock = clock or (lambda: datetime.now(timezone.utc))

        self._cached_draft: SourceJobDraft | None = None
        self._cached_issues: list[RecordIssue] = []

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        """Fetch the single manual record as an AdapterPage."""
        verify_runtime_config(self.effective_source, config)

        # If a continuation token is passed, manual text has already been consumed
        if continuation is not None:
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                continuation_out=None,
            )

        # 1. Resolve content bytes and text
        content_bytes: bytes | None = None
        input_ref = "manual://pasted_text"
        if self.text_path is not None:
            p = Path(self.text_path)
            if not p.is_absolute():
                if self.input_base_path is None:
                    raise ValueError(
                        "Relative text_path requires an explicit input_base_path"
                    )
                p = (self.input_base_path / p).resolve()
            input_ref = f"file://{p.as_posix()}"

            if not p.is_file():
                err = ClassifiedError.from_category(
                    category=ErrorCategory.STORAGE,
                    message=f"Input text file not found at: {p}",
                    details={"code": "input_file_not_found"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )
            try:
                content_bytes = p.read_bytes()
            except Exception as exc:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.STORAGE,
                    message=f"Failed to read input file: {exc}",
                    details={"code": "input_file_read_error"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )
            # Strict UTF-8 with BOM support
            try:
                posting_text = content_bytes.decode("utf-8-sig")
            except Exception as exc:
                issue = RecordIssue(
                    input_ref=input_ref,
                    input_hash=compute_content_hash(content_bytes),
                    record_index=1,
                    code="invalid_encoding",
                    severity="error",
                    message=f"Failed to decode text file as UTF-8: {exc}",
                    category=ErrorCategory.UNSUPPORTED_INPUT,
                )
                return AdapterPage(
                    items=[],
                    issues=[issue],
                    exhausted=True,
                )
        else:
            if self.raw_text is not None:
                posting_text = self.raw_text
                content_bytes = posting_text.encode("utf-8")
            else:
                posting_text = ""
                content_bytes = b""

        content_hash = compute_content_hash(content_bytes)

        # 2. Validate URL and Text
        issues: list[RecordIssue] = []
        is_url_valid, url_err = validate_http_url(self.source_url)
        if not is_url_valid:
            issues.append(
                RecordIssue(
                    input_ref=input_ref,
                    input_hash=content_hash,
                    record_index=1,
                    field_path="source_url",
                    code=f"invalid_source_url_{url_err}",
                    severity="error",
                    message=f"Source URL is invalid: {url_err}",
                    category=ErrorCategory.VALIDATION,
                )
            )

        if not posting_text or not posting_text.strip():
            issues.append(
                RecordIssue(
                    input_ref=input_ref,
                    input_hash=content_hash,
                    record_index=1,
                    field_path="text",
                    code="missing_posting_text",
                    severity="error",
                    message="Supplied posting text is empty or blank",
                    category=ErrorCategory.VALIDATION,
                )
            )

        # If blocking errors exist, capture payload if non-empty and return
        if any(iss.severity == "error" for iss in issues):
            raw_ref = input_ref
            if content_bytes:
                try:
                    raw_ref, _ = self.capture_sink.capture(
                        content_bytes, identifier_hint="manual_text_error"
                    )
                except Exception:
                    pass
            self._cached_issues = issues
            return AdapterPage(
                items=[],
                issues=issues,
                raw_response_refs=[raw_ref] if raw_ref != input_ref else [],
                exhausted=True,
            )

        # 3. Capture bytes in sink
        raw_payload_ref, captured_hash = self.capture_sink.capture(
            content_bytes, identifier_hint="manual_text"
        )

        # 4. Derive posting ID
        posting_id, _ = derive_manual_posting_id(
            self.source_posting_id, self.source_url
        )
        source_key = SourceKey(
            provider=self.effective_source.config.provider,
            board_id=self.effective_source.config.board_id,
            source_posting_id=posting_id,
        )

        fetch_time = self.clock()
        if fetch_time.tzinfo is None:
            fetch_time = fetch_time.replace(tzinfo=timezone.utc)
        else:
            fetch_time = fetch_time.astimezone(timezone.utc)

        raw_posting = RawPosting(
            raw_payload_ref=raw_payload_ref,
            raw_content_hash=captured_hash,
            source_key=source_key,
            fetch_time=fetch_time,
            raw_payload=posting_text,
        )

        # 5. Build draft mapping
        raw_data: dict[str, Any] = {
            "source_url": self.source_url,
            "text": posting_text,
            "title": self.title,
            "company": self.company,
            "application_url": self.application_url,
        }
        mapped_fields, mapping_issues = map_raw_record_to_draft_fields(
            raw_data,
            input_ref=raw_payload_ref,
            input_hash=captured_hash,
            record_index=1,
            source_key=source_key,
        )
        all_issues = issues + mapping_issues

        draft = SourceJobDraft(
            raw_reference=raw_payload_ref,
            source_key=source_key,
            fetch_time=fetch_time,
            original_fields=raw_data,
            source_mapped_fields=mapped_fields,
        )

        self._cached_draft = draft
        self._cached_issues = all_issues

        return AdapterPage(
            items=[raw_posting],
            issues=all_issues,
            raw_response_refs=[raw_payload_ref],
            exhausted=True,
            continuation_out=None,
        )

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        """Map a raw posting produced by this adapter into a DraftResult."""
        if self._cached_draft is not None and self._cached_draft.raw_reference == raw.raw_payload_ref:
            return DraftResult(
                raw_reference=raw.raw_payload_ref,
                draft=self._cached_draft,
                issues=self._cached_issues,
            )

        # Fallback: re-derive draft from raw payload
        raw_data: dict[str, Any] = {
            "source_url": self.source_url,
            "text": raw.raw_payload,
            "title": self.title,
            "company": self.company,
            "application_url": self.application_url,
        }
        mapped_fields, mapping_issues = map_raw_record_to_draft_fields(
            raw_data,
            input_ref=raw.raw_payload_ref,
            input_hash=raw.raw_content_hash,
            record_index=1,
            source_key=raw.source_key,
        )
        has_errors = any(iss.severity == "error" for iss in mapping_issues)
        draft = None
        if not has_errors:
            draft = SourceJobDraft(
                raw_reference=raw.raw_payload_ref,
                source_key=raw.source_key,
                fetch_time=raw.fetch_time,
                original_fields=raw_data,
                source_mapped_fields=mapped_fields,
            )
        return DraftResult(
            raw_reference=raw.raw_payload_ref,
            draft=draft,
            issues=mapping_issues,
        )
