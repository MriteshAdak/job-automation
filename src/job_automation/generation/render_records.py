"""Versioned rendering contracts, specifications, receipts, and artifact sets (GEN-05-S01)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import DocumentType
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.primitives import UtcDatetime


def canonical_json_dumps(data: Any) -> str:
    """Produce deterministic UTF-8 JSON serialization with sorted keys and normalized delimiters."""
    def _default(obj: Any) -> Any:
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.astimezone(timezone.utc).isoformat()
        if hasattr(obj, "value"):
            return obj.value
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(data, default=_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_sha256_digest(data: Any) -> str:
    """Compute sha256:<hex> content digest over canonical JSON payload."""
    payload = canonical_json_dumps(data)
    hex_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{hex_digest}"


def compute_file_sha256(file_path: Path) -> str:
    """Compute sha256:<hex> content digest over exact file bytes."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


class PageSetup(ContractModel):
    """Page layout dimensions and margins in millimeters."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    page_size: Literal["A4", "LETTER"] = "A4"
    page_width_mm: float = Field(default=210.0, gt=0)
    page_height_mm: float = Field(default=297.0, gt=0)
    margin_top_mm: float = Field(default=20.0, ge=10.0, le=40.0)
    margin_bottom_mm: float = Field(default=20.0, ge=10.0, le=40.0)
    margin_left_mm: float = Field(default=20.0, ge=10.0, le=40.0)
    margin_right_mm: float = Field(default=20.0, ge=10.0, le=40.0)


class TypographySetup(ContractModel):
    """Typography and font sizing rules for approved layout."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    primary_font: str = Field(default="Calibri", min_length=1)
    fallback_fonts: list[str] = Field(
        default_factory=lambda: ["Arial", "Liberation Sans", "DejaVu Sans"]
    )
    body_font_size_pt: float = Field(default=11.0, ge=10.0, le=14.0)
    heading1_font_size_pt: float = Field(default=16.0, ge=12.0, le=24.0)
    heading2_font_size_pt: float = Field(default=13.0, ge=11.0, le=18.0)
    heading3_font_size_pt: float = Field(default=11.5, ge=10.0, le=16.0)
    small_font_size_pt: float = Field(default=9.0, ge=8.0, le=11.0)
    line_spacing: float = Field(default=1.15, ge=1.0, le=2.0)


class ApprovedLayout(ContractModel):
    """Approved document layout specifications and typography (GEN-05-S02)."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    layout_id: str = Field(min_length=1)
    layout_version: str = Field(default="1.0.0")
    document_type: DocumentType
    supported_languages: list[str] = Field(default_factory=lambda: ["de", "en"])
    supported_content_specs: list[str] = Field(
        default_factory=lambda: ["content-basic", "content-compact"]
    )
    page_setup: PageSetup = Field(default_factory=PageSetup)
    typography: TypographySetup = Field(default_factory=TypographySetup)
    draft_notices: dict[str, str] = Field(
        default_factory=lambda: {
            "de": "Entwurf – vor Verwendung prüfen",
            "en": "Draft – review before use",
        }
    )
    approved_by: str = Field(min_length=1)
    approved_at: UtcDatetime
    approval_notes: str = Field(default="")
    is_approved: Literal[True] = True
    layout_digest: str = Field(default="")

    def model_post_init(self, __context: Any) -> None:
        if not self.layout_digest:
            data = self.model_dump(exclude={"layout_digest"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "layout_digest", digest)


class RenderSpecification(ContractModel):
    """Frozen render specification binding draft, report, and layout before conversion."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    spec_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    draft_id: uuid.UUID
    draft_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    report_id: uuid.UUID
    report_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    layout_id: str = Field(min_length=1)
    layout_version: str = Field(min_length=1)
    layout_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    requested_formats: list[Literal["docx", "pdf"]] = Field(
        default_factory=lambda: ["docx", "pdf"]
    )
    target_language: str = Field(default="de")
    created_at: UtcDatetime
    spec_hash: str = Field(default="")

    def model_post_init(self, __context: Any) -> None:
        if not self.spec_hash:
            data = self.model_dump(exclude={"spec_hash"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "spec_hash", digest)


class RenderIntent(ContractModel):
    """Durable intent tracking physical rendering lifecycle for a request."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    intent_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    logical_key: str = Field(min_length=1)
    spec_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    artifact_version: int = Field(default=1, ge=1)
    target_formats: list[Literal["docx", "pdf"]]
    status: Literal["pending", "in_progress", "completed", "failed", "blocked"] = "pending"
    created_at: UtcDatetime
    updated_at: UtcDatetime


class RenderAttempt(ContractModel):
    """Audit record for a bounded execution attempt converting a single format."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    attempt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    intent_id: uuid.UUID
    request_id: uuid.UUID
    attempt_number: int = Field(ge=1)
    format: Literal["docx", "pdf"]
    staging_dir: str
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    status: Literal["started", "completed", "failed", "timed_out"] = "started"
    exit_code: int | None = None
    duration_ms: int | None = None
    error_json: dict[str, Any] | None = None


class RenderedArtifactReceipt(ContractModel):
    """Immutable receipt binding exact rendered file bytes to specification and report."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    receipt_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_set_id: uuid.UUID
    format: Literal["docx", "pdf"]
    version: int = Field(default=1, ge=1)
    content_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    size_bytes: int = Field(gt=0)
    local_path: str = Field(min_length=1)
    relative_managed_path: str = Field(min_length=1)
    spec_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    draft_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    report_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    layout_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    docx_artifact_id: uuid.UUID | None = None
    docx_content_hash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    output_checks: dict[str, Any] = Field(default_factory=dict)
    created_at: UtcDatetime
    receipt_hash: str = Field(default="")

    def model_post_init(self, __context: Any) -> None:
        if self.format == "pdf" and not self.docx_artifact_id:
            raise ValueError("PDF receipt must reference source docx_artifact_id")
        if not self.receipt_hash:
            data = self.model_dump(exclude={"receipt_hash"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "receipt_hash", digest)


class ArtifactSet(ContractModel):
    """Complete set of required physical rendered formats for a GenerationRequest."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    set_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    request_id: uuid.UUID
    set_version: int = Field(default=1, ge=1)
    required_formats: list[Literal["docx", "pdf"]]
    artifacts: dict[str, RenderedArtifactReceipt] = Field(default_factory=dict)
    is_complete: bool = False
    report_id: uuid.UUID
    report_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    draft_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    set_hash: str = Field(default="")
    created_at: UtcDatetime

    def model_post_init(self, __context: Any) -> None:
        complete = all(fmt in self.artifacts for fmt in self.required_formats)
        object.__setattr__(self, "is_complete", complete)
        if not self.set_hash:
            data = self.model_dump(exclude={"set_hash"})
            digest = compute_sha256_digest(data)
            object.__setattr__(self, "set_hash", digest)


class LocalRenderResult(ContractModel):
    """Outcome of render_or_reopen operation."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["completed", "blocked", "failed"]
    artifact_set: ArtifactSet | None = None
    error: ClassifiedError | None = None
    reason_code: str | None = None
    partial_receipts: list[RenderedArtifactReceipt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> LocalRenderResult:
        if self.status == "completed" and (self.artifact_set is None or not self.artifact_set.is_complete):
            raise ValueError("Completed render result requires a complete ArtifactSet")
        if self.status in ("blocked", "failed") and self.error is None:
            raise ValueError("Blocked or failed render result requires ClassifiedError")
        return self


def export_schemas(output_dir: Path) -> list[Path]:
    """Export JSON Schema definitions for GEN-05 contracts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []

    models = [
        ("approved_layout.schema.json", ApprovedLayout),
        ("render_specification.schema.json", RenderSpecification),
        ("render_intent.schema.json", RenderIntent),
        ("render_attempt.schema.json", RenderAttempt),
        ("rendered_artifact_receipt.schema.json", RenderedArtifactReceipt),
        ("artifact_set.schema.json", ArtifactSet),
        ("local_render_result.schema.json", LocalRenderResult),
    ]

    for fname, model_cls in models:
        p = output_dir / fname
        schema = model_cls.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://job-automation.local/schemas/v1/{fname}"
        p.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        exported.append(p)

    return exported
