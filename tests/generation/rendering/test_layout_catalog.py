"""Unit tests for approved layout catalog and layout pinning (GEN-05-S02)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.contracts.enums import DocumentType
from job_automation.contracts.errors import ErrorCategory
from job_automation.generation.layout_catalog import (
    LAYOUT_CV_BASIC_A4,
    LAYOUT_CV_COMPACT_A4,
    LAYOUT_LETTER_BASIC_A4,
    LAYOUT_LETTER_COMPACT_A4,
    LayoutCatalog,
)
from job_automation.generation.render_records import ApprovedLayout


def test_standard_layouts_valid():
    catalog = LayoutCatalog()
    for layout in [LAYOUT_CV_BASIC_A4, LAYOUT_CV_COMPACT_A4, LAYOUT_LETTER_BASIC_A4, LAYOUT_LETTER_COMPACT_A4]:
        found = catalog.get_layout(layout.layout_id)
        assert found is not None
        assert found.is_approved is True
        assert found.typography.body_font_size_pt >= 10.0
        assert found.layout_digest.startswith("sha256:")
        assert "de" in found.draft_notices
        assert "en" in found.draft_notices


def test_find_compatible_layout():
    catalog = LayoutCatalog()

    # CV basic de
    layout, err = catalog.find_compatible_layout(DocumentType.CV, "content-basic", "de")
    assert err is None
    assert layout is not None
    assert layout.layout_id == "layout-cv-basic-a4"

    # CV compact en
    layout, err = catalog.find_compatible_layout(DocumentType.CV, "content-compact", "en")
    assert err is None
    assert layout is not None
    assert layout.layout_id == "layout-cv-compact-a4"

    # Letter basic de
    layout, err = catalog.find_compatible_layout(DocumentType.COVER_LETTER, "content-basic", "de")
    assert err is None
    assert layout is not None
    assert layout.layout_id == "layout-letter-basic-a4"

    # Unsupported content spec
    layout, err = catalog.find_compatible_layout(DocumentType.CV, "content-unsupported", "de")
    assert layout is None
    assert err is not None
    assert err.category == ErrorCategory.MISSING_CONFIGURATION
    assert err.details is not None
    assert err.details.get("code") == "layout_unavailable"


def test_pin_layout_immutability(tmp_path: Path):
    catalog = LayoutCatalog()
    req_id = uuid.uuid4()

    # Pin layout initially
    pinned = catalog.pin_layout(req_id, LAYOUT_CV_BASIC_A4, tmp_path)
    assert pinned.layout_digest == LAYOUT_CV_BASIC_A4.layout_digest

    # Subsequent pin of identical layout succeeds
    re_pinned = catalog.pin_layout(req_id, LAYOUT_CV_BASIC_A4, tmp_path)
    assert re_pinned.layout_digest == LAYOUT_CV_BASIC_A4.layout_digest

    # Attempt to pin a modified layout under same request fails
    tampered_layout = LAYOUT_CV_BASIC_A4.model_copy(
        update={"approval_notes": "Tampered notes", "layout_digest": "sha256:" + "9" * 64}
    )
    with pytest.raises(ValueError, match="Pinned layout digest conflict"):
        catalog.pin_layout(req_id, tampered_layout, tmp_path)
