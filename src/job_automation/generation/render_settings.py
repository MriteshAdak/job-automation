"""Configuration settings for GEN-05 rendering and conversion."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from job_automation.contracts.base import ContractModel


class RenderingSettings(ContractModel):
    """Configuration settings for document layout, LibreOffice conversion, and output verification."""

    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)
    schema_version: Literal["1.0"] = "1.0"
    catalog_dir: Path | None = None
    libreoffice_path: Path | None = None
    conversion_timeout_seconds: int = Field(default=120, gt=0, le=600)
    cleanup_grace_seconds: int = Field(default=10, gt=0, le=60)
    max_render_attempts: int = Field(default=5, gt=0, le=20)
    default_formats: list[Literal["docx", "pdf"]] = Field(
        default_factory=lambda: ["docx", "pdf"]
    )
    body_font_min_size_pt: float = Field(default=10.0, ge=8.0, le=12.0)
    allowed_fonts: list[str] = Field(
        default_factory=lambda: ["Calibri", "Arial", "Liberation Sans", "DejaVu Sans"]
    )

