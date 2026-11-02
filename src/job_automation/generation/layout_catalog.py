"""Approved layout catalog and layout pinning service (GEN-05-S02)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from job_automation.contracts.enums import DocumentType
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.render_records import (
    ApprovedLayout,
    PageSetup,
    TypographySetup,
    canonical_json_dumps,
    compute_sha256_digest,
)

APPROVAL_TIMESTAMP = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)
DEFAULT_APPROVER = "system-approved-baseline-v1"

# -----------------------------------------------------------------------------
# Baseline Approved Layout Definitions
# -----------------------------------------------------------------------------

LAYOUT_CV_BASIC_A4 = ApprovedLayout(
    layout_id="layout-cv-basic-a4",
    layout_version="1.0.0",
    document_type=DocumentType.CV,
    supported_languages=["de", "en"],
    supported_content_specs=["content-basic"],
    page_setup=PageSetup(
        page_size="A4",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_top_mm=20.0,
        margin_bottom_mm=20.0,
        margin_left_mm=20.0,
        margin_right_mm=20.0,
    ),
    typography=TypographySetup(
        primary_font="Calibri",
        fallback_fonts=["Arial", "Liberation Sans", "DejaVu Sans"],
        body_font_size_pt=11.0,
        heading1_font_size_pt=16.0,
        heading2_font_size_pt=13.0,
        heading3_font_size_pt=11.5,
        small_font_size_pt=9.0,
        line_spacing=1.15,
    ),
    draft_notices={
        "de": "Entwurf – vor Verwendung prüfen",
        "en": "Draft – review before use",
    },
    approved_by=DEFAULT_APPROVER,
    approved_at=APPROVAL_TIMESTAMP,
    approval_notes="Baseline approved single-column A4 CV layout with 11pt body text.",
)

LAYOUT_CV_COMPACT_A4 = ApprovedLayout(
    layout_id="layout-cv-compact-a4",
    layout_version="1.0.0",
    document_type=DocumentType.CV,
    supported_languages=["de", "en"],
    supported_content_specs=["content-compact"],
    page_setup=PageSetup(
        page_size="A4",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_top_mm=15.0,
        margin_bottom_mm=15.0,
        margin_left_mm=15.0,
        margin_right_mm=15.0,
    ),
    typography=TypographySetup(
        primary_font="Calibri",
        fallback_fonts=["Arial", "Liberation Sans", "DejaVu Sans"],
        body_font_size_pt=10.0,
        heading1_font_size_pt=14.0,
        heading2_font_size_pt=12.0,
        heading3_font_size_pt=10.5,
        small_font_size_pt=8.5,
        line_spacing=1.1,
    ),
    draft_notices={
        "de": "Entwurf – vor Verwendung prüfen",
        "en": "Draft – review before use",
    },
    approved_by=DEFAULT_APPROVER,
    approved_at=APPROVAL_TIMESTAMP,
    approval_notes="Baseline approved compact single-column A4 CV layout with 10pt body text.",
)

LAYOUT_LETTER_BASIC_A4 = ApprovedLayout(
    layout_id="layout-letter-basic-a4",
    layout_version="1.0.0",
    document_type=DocumentType.COVER_LETTER,
    supported_languages=["de", "en"],
    supported_content_specs=["content-basic"],
    page_setup=PageSetup(
        page_size="A4",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_top_mm=25.0,
        margin_bottom_mm=20.0,
        margin_left_mm=25.0,
        margin_right_mm=20.0,
    ),
    typography=TypographySetup(
        primary_font="Calibri",
        fallback_fonts=["Arial", "Liberation Sans", "DejaVu Sans"],
        body_font_size_pt=11.0,
        heading1_font_size_pt=16.0,
        heading2_font_size_pt=13.0,
        heading3_font_size_pt=11.5,
        small_font_size_pt=9.0,
        line_spacing=1.15,
    ),
    draft_notices={
        "de": "Entwurf – vor Verwendung prüfen",
        "en": "Draft – review before use",
    },
    approved_by=DEFAULT_APPROVER,
    approved_at=APPROVAL_TIMESTAMP,
    approval_notes="Baseline approved standard DIN-compatible A4 cover letter layout with 11pt body text.",
)

LAYOUT_LETTER_COMPACT_A4 = ApprovedLayout(
    layout_id="layout-letter-compact-a4",
    layout_version="1.0.0",
    document_type=DocumentType.COVER_LETTER,
    supported_languages=["de", "en"],
    supported_content_specs=["content-compact"],
    page_setup=PageSetup(
        page_size="A4",
        page_width_mm=210.0,
        page_height_mm=297.0,
        margin_top_mm=20.0,
        margin_bottom_mm=18.0,
        margin_left_mm=20.0,
        margin_right_mm=18.0,
    ),
    typography=TypographySetup(
        primary_font="Calibri",
        fallback_fonts=["Arial", "Liberation Sans", "DejaVu Sans"],
        body_font_size_pt=10.5,
        heading1_font_size_pt=14.0,
        heading2_font_size_pt=12.0,
        heading3_font_size_pt=11.0,
        small_font_size_pt=8.5,
        line_spacing=1.1,
    ),
    draft_notices={
        "de": "Entwurf – vor Verwendung prüfen",
        "en": "Draft – review before use",
    },
    approved_by=DEFAULT_APPROVER,
    approved_at=APPROVAL_TIMESTAMP,
    approval_notes="Baseline approved compact A4 cover letter layout with 10.5pt body text.",
)

STANDARD_LAYOUTS: dict[str, ApprovedLayout] = {
    LAYOUT_CV_BASIC_A4.layout_id: LAYOUT_CV_BASIC_A4,
    LAYOUT_CV_COMPACT_A4.layout_id: LAYOUT_CV_COMPACT_A4,
    LAYOUT_LETTER_BASIC_A4.layout_id: LAYOUT_LETTER_BASIC_A4,
    LAYOUT_LETTER_COMPACT_A4.layout_id: LAYOUT_LETTER_COMPACT_A4,
}


class LayoutCatalog:
    """Catalog of approved layouts with selection and immutable snapshot pinning."""

    def __init__(self, catalog: Mapping[str, ApprovedLayout] | None = None) -> None:
        self._catalog = dict(catalog if catalog is not None else STANDARD_LAYOUTS)

    def get_layout(self, layout_id: str) -> ApprovedLayout | None:
        """Lookup an approved layout by its unique identifier."""
        layout = self._catalog.get(layout_id)
        if layout and layout.is_approved:
            return layout
        return None

    def find_compatible_layout(
        self,
        document_type: DocumentType,
        content_spec: str,
        language: str,
    ) -> tuple[ApprovedLayout | None, ClassifiedError | None]:
        """Find an approved layout compatible with document type, content specification, and language."""
        for layout in self._catalog.values():
            if not layout.is_approved:
                continue
            if layout.document_type != document_type:
                continue
            if content_spec not in layout.supported_content_specs:
                continue
            if language not in layout.supported_languages:
                continue
            return layout, None

        return None, ClassifiedError.from_category(
            category=ErrorCategory.MISSING_CONFIGURATION,
            message=(
                f"No approved layout found compatible with document_type='{document_type.value}', "
                f"content_spec='{content_spec}', language='{language}'"
            ),
            details={"code": "layout_unavailable"},
        )

    def pin_layout(
        self,
        request_id: uuid.UUID,
        layout: ApprovedLayout,
        storage_base_dir: Path,
    ) -> ApprovedLayout:
        """Persist an immutable layout snapshot for a request at first render intent."""
        pin_dir = storage_base_dir / "pinned_layouts" / str(request_id)
        pin_dir.mkdir(parents=True, exist_ok=True)
        pin_file = pin_dir / f"{layout.layout_id}_{layout.layout_version}.json"

        if pin_file.is_file():
            # If already pinned, reload and verify digest
            existing_data = json.loads(pin_file.read_text(encoding="utf-8"))
            existing = ApprovedLayout.model_validate(existing_data)
            if existing.layout_digest != layout.layout_digest:
                raise ValueError(
                    f"Pinned layout digest conflict for request {request_id}: "
                    f"expected {existing.layout_digest}, got {layout.layout_digest}"
                )
            return existing

        # Write fresh snapshot
        pin_file.write_text(canonical_json_dumps(layout.model_dump()), encoding="utf-8")
        return layout
