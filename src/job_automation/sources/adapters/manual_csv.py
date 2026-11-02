"""Manual CSV adapter implementation (SOURCE-02-S05).

Imports job postings from local CSV files or bytes with:
- Strict standard CSV parsing (comma default, explicit semicolon option).
- Exact preservation of row data (BOM, quotes, multiline descriptions, leading zeros, formulas).
- Header validation (missing required columns, duplicate headers, empty headers).
- Bounded pagination and input-hash-bound continuation.
- Record-level error isolation: corrupt or malformed rows do not block valid rows.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
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
from job_automation.sources.adapters.continuation import validate_continuation
from job_automation.sources.adapters.manual_identity import (
    derive_manual_posting_id,
    validate_http_url,
)
from job_automation.sources.adapters.mapping import map_raw_record_to_draft_fields
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash
from job_automation.sources.models import EffectiveSource


class ManualCsvAdapter(Adapter):
    """Adapter for importing job postings from a CSV file or byte stream."""

    def __init__(
        self,
        effective_source: EffectiveSource,
        capture_sink: RawCaptureSink,
        csv_path: Path | str | None = None,
        csv_bytes: bytes | None = None,
        input_base_path: Path | None = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
        page_size: int = 50,
        column_mapping: dict[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        validate_adapter_binding(
            effective_source,
            supported_method=AcquisitionMethod.MANUAL_IMPORT,
            adapter_name="manual_csv",
        )
        if page_size < 1:
            raise ValueError(f"page_size must be positive, got {page_size}")

        self.effective_source = effective_source
        self.capture_sink = capture_sink
        self.csv_path = csv_path
        self.csv_bytes = csv_bytes
        self.input_base_path = input_base_path
        self.delimiter = delimiter
        self.encoding = encoding
        self.page_size = page_size
        self.column_mapping = column_mapping or {}
        self.clock = clock or (lambda: datetime.now(timezone.utc))

        self._cached_drafts: dict[str, tuple[SourceJobDraft | None, list[RecordIssue]]] = {}

    def _compute_options_hash(self) -> str:
        data = {
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "page_size": self.page_size,
            "column_mapping": self.column_mapping,
        }
        json_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        return f"sha256:{hashlib.sha256(json_bytes).hexdigest()}"

    def fetch_page(
        self,
        config: SourceConfig,
        continuation: Continuation | None = None,
    ) -> AdapterPage:
        """Fetch a page of raw postings from the CSV input."""
        verify_runtime_config(self.effective_source, config)

        # 1. Resolve CSV bytes
        input_ref = "manual://csv_bytes"
        if self.csv_path is not None:
            p = Path(self.csv_path)
            # Reject unsupported file formats like .xlsx explicitly
            if p.suffix.lower() in {".xlsx", ".xls", ".ods"}:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.UNSUPPORTED_INPUT,
                    message=f"Unsupported spreadsheet format '{p.suffix}'; only CSV is supported",
                    details={"code": "unsupported_format"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )

            if not p.is_absolute():
                if self.input_base_path is None:
                    raise ValueError(
                        "Relative csv_path requires an explicit input_base_path"
                    )
                p = (self.input_base_path / p).resolve()
            input_ref = f"file://{p.as_posix()}"

            if not p.is_file():
                err = ClassifiedError.from_category(
                    category=ErrorCategory.STORAGE,
                    message=f"CSV file not found at: {p}",
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
                    message=f"Failed to read CSV file: {exc}",
                    details={"code": "input_file_read_error"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )
        elif self.csv_bytes is not None:
            content_bytes = self.csv_bytes
        else:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="No CSV file or bytes provided to ManualCsvAdapter",
                details={"code": "missing_csv_input"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        if len(content_bytes) == 0:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="CSV file is empty (0 bytes)",
                details={"code": "empty_csv_file"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        # 2. Capture raw parent file in sink
        parent_ref, parent_hash = self.capture_sink.capture(
            content_bytes, identifier_hint="manual_csv"
        )
        options_hash = self._compute_options_hash()

        # 3. Validate continuation if provided
        start_record_index = 1
        if continuation is not None:
            issues = validate_continuation(
                continuation,
                expected_source_key=config.source_key,
                expected_scope_id=self.effective_source.inventory_scope.scope_id,
                expected_adapter_name="manual_csv",
                expected_input_hash=parent_hash,
                expected_options_hash=options_hash,
            )
            if issues:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Continuation token invalid: {issues[0].message}",
                    details={"code": "invalid_continuation"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )
            try:
                start_record_index = int(continuation.value)
            except ValueError:
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Continuation value '{continuation.value}' is not a valid integer record index",
                    details={"code": "invalid_continuation_value"},
                )
                return AdapterPage(
                    items=[],
                    issues=[],
                    exhausted=True,
                    page_error=err,
                )

        # 4. Decode CSV text with UTF-8 BOM tolerance
        try:
            # Use utf-8-sig to handle both UTF-8 with BOM and standard UTF-8 cleanly
            text_content = content_bytes.decode(
                "utf-8-sig" if self.encoding in {"utf-8", "utf-8-sig"} else self.encoding
            )
        except Exception as exc:
            issue = RecordIssue(
                input_ref=parent_ref,
                input_hash=parent_hash,
                record_index=1,
                code="invalid_encoding",
                severity="error",
                message=f"CSV decoding failed with encoding '{self.encoding}': {exc}",
                category=ErrorCategory.UNSUPPORTED_INPUT,
            )
            return AdapterPage(
                items=[],
                issues=[issue],
                exhausted=True,
            )

        # 5. Parse header and validate
        reader = csv.reader(io.StringIO(text_content), delimiter=self.delimiter)
        try:
            raw_headers = next(reader)
        except StopIteration:
            # Header-only or empty
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="CSV contains no header line",
                details={"code": "missing_header"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )
        except csv.Error as exc:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"CSV parse error on header: {exc}",
                details={"code": "csv_parse_error"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        # Clean headers and detect duplicates / empty headings
        headers = [h.lstrip("\ufeff").strip() for h in raw_headers]
        if any(h == "" for h in headers):
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="CSV contains one or more empty column headers",
                details={"code": "empty_csv_header"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        if len(headers) != len(set(headers)):
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="CSV contains duplicate column headers",
                details={"code": "duplicate_csv_header"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        # Map inverted column mapping (csv_header -> canonical_field)
        inv_mapping = {v: k for k, v in self.column_mapping.items()}
        canonical_headers = [inv_mapping.get(h, h) for h in headers]

        # Verify required columns
        required_cols = {"source_url", "text"}
        missing_required = required_cols - set(canonical_headers)
        if missing_required:
            err = ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"CSV is missing required column(s): {', '.join(sorted(missing_required))}",
                details={"code": "missing_required_column"},
            )
            return AdapterPage(
                items=[],
                issues=[],
                exhausted=True,
                page_error=err,
            )

        # 6. Parse rows and collect logical records
        fetch_time = self.clock()
        if fetch_time.tzinfo is None:
            fetch_time = fetch_time.replace(tzinfo=timezone.utc)
        else:
            fetch_time = fetch_time.astimezone(timezone.utc)

        all_page_items: list[RawPosting] = []
        all_page_issues: list[RecordIssue] = []
        logical_index = 0
        last_line_num = 1  # Header was line 1
        has_more = False

        for row in reader:
            current_line_num = reader.line_num
            line_start = last_line_num + 1
            line_end = current_line_num
            last_line_num = current_line_num

            # Check if row is purely blank
            if not row or all(c.strip() == "" for c in row):
                continue

            logical_index += 1

            # Only process records within the current page window
            if logical_index < start_record_index:
                continue
            if logical_index >= start_record_index + self.page_size:
                has_more = True
                break

            # Check column count
            if len(row) != len(headers):
                all_page_issues.append(
                    RecordIssue(
                        input_ref=parent_ref,
                        input_hash=parent_hash,
                        record_index=logical_index,
                        line_start=line_start,
                        line_end=line_end,
                        code="csv_column_mismatch",
                        severity="error",
                        message=f"Row has {len(row)} cells; expected {len(headers)} columns",
                        category=ErrorCategory.VALIDATION,
                    )
                )
                continue

            # Build row dict preserving exact strings
            row_dict: dict[str, Any] = {}
            for col_name, cell_value in zip(canonical_headers, row):
                row_dict[col_name] = cell_value

            source_url = row_dict.get("source_url", "").strip()
            text_content = row_dict.get("text", "")
            explicit_id = row_dict.get("source_posting_id", "").strip() or None

            # Validate URL
            is_url_valid, url_err = validate_http_url(source_url)
            row_issues: list[RecordIssue] = []
            if not is_url_valid:
                row_issues.append(
                    RecordIssue(
                        input_ref=parent_ref,
                        input_hash=parent_hash,
                        record_index=logical_index,
                        line_start=line_start,
                        line_end=line_end,
                        field_path="source_url",
                        code=f"invalid_source_url_{url_err}",
                        severity="error",
                        message=f"Source URL is invalid: {url_err}",
                        category=ErrorCategory.VALIDATION,
                    )
                )

            # Validate text
            if not text_content or not str(text_content).strip():
                row_issues.append(
                    RecordIssue(
                        input_ref=parent_ref,
                        input_hash=parent_hash,
                        record_index=logical_index,
                        line_start=line_start,
                        line_end=line_end,
                        field_path="text",
                        code="missing_posting_text",
                        severity="error",
                        message="Job posting text is empty",
                        category=ErrorCategory.VALIDATION,
                    )
                )

            all_page_issues.extend(row_issues)
            if any(iss.severity == "error" for iss in row_issues):
                continue

            # Derive posting ID
            posting_id, _ = derive_manual_posting_id(explicit_id, source_url)
            source_key = SourceKey(
                provider=self.effective_source.config.provider,
                board_id=self.effective_source.config.board_id,
                source_posting_id=posting_id,
            )

            # Create RawPosting for this row
            row_payload_json = json.dumps(row_dict, ensure_ascii=False)
            row_bytes = row_payload_json.encode("utf-8")
            row_ref, row_hash = self.capture_sink.capture(
                row_bytes, identifier_hint=f"csv_r{logical_index}"
            )

            raw_posting = RawPosting(
                raw_payload_ref=row_ref,
                raw_content_hash=row_hash,
                source_key=source_key,
                fetch_time=fetch_time,
                raw_payload=row_payload_json,
            )
            all_page_items.append(raw_posting)

            # Map draft fields and cache for draft_posting
            mapped_fields, mapping_issues = map_raw_record_to_draft_fields(
                row_dict,
                input_ref=row_ref,
                input_hash=row_hash,
                record_index=logical_index,
                source_key=source_key,
            )
            all_page_issues.extend(mapping_issues)

            draft = SourceJobDraft(
                raw_reference=row_ref,
                source_key=source_key,
                fetch_time=fetch_time,
                original_fields=row_dict,
                source_mapped_fields=mapped_fields,
            )
            self._cached_drafts[row_ref] = (draft, mapping_issues)

        continuation_out = None
        if has_more:
            next_start = start_record_index + self.page_size
            continuation_out = Continuation(
                kind="local_record",
                value=str(next_start),
                source_key=config.source_key,
                scope_id=self.effective_source.inventory_scope.scope_id,
                adapter_name="manual_csv",
                input_hash=parent_hash,
                options_hash=options_hash,
            )

        return AdapterPage(
            items=all_page_items,
            issues=all_page_issues,
            raw_response_refs=[parent_ref],
            continuation_in=continuation,
            continuation_out=continuation_out,
            exhausted=continuation_out is None,
        )

    def draft_posting(self, raw: RawPosting) -> DraftResult:
        """Map a raw posting produced by this CSV adapter into a DraftResult."""
        if raw.raw_payload_ref in self._cached_drafts:
            draft, issues = self._cached_drafts[raw.raw_payload_ref]
            return DraftResult(
                raw_reference=raw.raw_payload_ref,
                draft=draft,
                issues=issues,
            )

        # Fallback: parse raw_payload as JSON dictionary
        try:
            row_dict = json.loads(raw.raw_payload)
        except Exception:
            row_dict = {"raw": raw.raw_payload}

        mapped_fields, mapping_issues = map_raw_record_to_draft_fields(
            row_dict,
            input_ref=raw.raw_payload_ref,
            input_hash=raw.raw_content_hash,
            source_key=raw.source_key,
        )
        has_errors = any(iss.severity == "error" for iss in mapping_issues)
        draft = None
        if not has_errors:
            draft = SourceJobDraft(
                raw_reference=raw.raw_payload_ref,
                source_key=raw.source_key,
                fetch_time=raw.fetch_time,
                original_fields=row_dict,
                source_mapped_fields=mapped_fields,
            )
        return DraftResult(
            raw_reference=raw.raw_payload_ref,
            draft=draft,
            issues=mapping_issues,
        )
