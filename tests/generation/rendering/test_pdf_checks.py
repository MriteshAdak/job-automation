"""Unit tests for PDF verification and failure conditions (GEN-05-S04)."""
from __future__ import annotations

from pathlib import Path

import pypdf

from job_automation.contracts.enums import DocumentType
from job_automation.generation.pdf_checks import verify_pdf_file
from tests.generation.rendering.test_docx_renderer import _build_test_draft


def _create_minimal_valid_pdf(output_path: Path, text: str) -> None:
    """Create a minimal valid PDF using pypdf writer for verification tests."""
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=595, height=842)  # A4

    # Add an annotation or text
    # In pypdf, we can write a page with content stream
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        writer.write(f)


def test_pdf_checks_missing_file(tmp_path: Path):
    draft = _build_test_draft()
    valid, checks, err = verify_pdf_file(tmp_path / "nonexistent.pdf", "sha256:123", draft)
    assert valid is False
    assert "does not exist" in err


def test_pdf_checks_invalid_signature(tmp_path: Path):
    draft = _build_test_draft()
    bad_pdf = tmp_path / "bad_sig.pdf"
    bad_pdf.write_bytes(b"NOT_A_PDF_FILE_HEADER_GARBAGE" * 10)

    valid, checks, err = verify_pdf_file(bad_pdf, "sha256:123", draft)
    assert valid is False
    assert "Invalid PDF signature header" in err


def test_pdf_checks_empty_text(tmp_path: Path):
    draft = _build_test_draft()
    blank_pdf = tmp_path / "blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with blank_pdf.open("wb") as f:
        writer.write(f)

    valid, checks, err = verify_pdf_file(blank_pdf, "sha256:123", draft)
    assert valid is False
    assert "All PDF pages returned empty text" in err

