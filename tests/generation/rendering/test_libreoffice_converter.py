"""Unit tests for headless LibreOffice PDF converter error handling and lifecycle (GEN-05-S04)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.generation.libreoffice_converter import LibreOfficeConverter
from job_automation.generation.render_settings import RenderingSettings
from tests.generation.rendering.test_docx_renderer import _build_test_draft


def test_converter_missing_executable(tmp_path: Path):
    nonexistent = tmp_path / "bin" / "soffice.com"
    settings = RenderingSettings(libreoffice_path=nonexistent)
    converter = LibreOfficeConverter(settings)

    draft = _build_test_draft()
    docx_file = tmp_path / "test.docx"
    docx_file.write_text("dummy")

    pdf_path, checks, err = converter.convert_docx_to_pdf(
        saved_docx_path=docx_file,
        attempt_dir=tmp_path / "attempt",
        expected_draft=draft,
        docx_hash="sha256:" + "0" * 64,
    )

    assert pdf_path is None
    assert err is not None
    assert err.category == ErrorCategory.MISSING_CONFIGURATION
    assert err.details.get("code") == "renderer_missing"
    assert "soffice.com" in err.message


def test_converter_timeout_classification(tmp_path: Path):
    # Create a fake executable (a python script that sleeps longer than timeout)
    script = tmp_path / "fake_soffice.py"
    script.write_text("import time; time.sleep(10)")

    # Wrapper batch/cmd on Windows
    fake_exe = tmp_path / "fake_soffice.bat"
    fake_exe.write_text(f'@"{sys.executable}" "{script}" %*\n')

    settings = RenderingSettings(
        libreoffice_path=fake_exe,
        conversion_timeout_seconds=1,  # Short timeout for testing!
        cleanup_grace_seconds=2,
    )
    converter = LibreOfficeConverter(settings)

    draft = _build_test_draft()
    docx_file = tmp_path / "test.docx"
    docx_file.write_text("dummy")

    pdf_path, checks, err = converter.convert_docx_to_pdf(
        saved_docx_path=docx_file,
        attempt_dir=tmp_path / "attempt",
        expected_draft=draft,
        docx_hash="sha256:" + "0" * 64,
    )

    assert pdf_path is None
    assert err is not None
    assert err.category == ErrorCategory.TRANSIENT_SERVICE
    assert err.details.get("code") == "renderer_timeout"


def test_converter_nonzero_exit_classification(tmp_path: Path):
    # Create a fake executable that exits with code 42
    script = tmp_path / "fake_fail.py"
    script.write_text("import sys; sys.stderr.write('Fatal crash in filter'); sys.exit(42)")

    fake_exe = tmp_path / "fake_fail.bat"
    fake_exe.write_text(f'@"{sys.executable}" "{script}" %*\n')

    settings = RenderingSettings(
        libreoffice_path=fake_exe,
        conversion_timeout_seconds=5,
    )
    converter = LibreOfficeConverter(settings)

    draft = _build_test_draft()
    docx_file = tmp_path / "test.docx"
    docx_file.write_text("dummy")

    pdf_path, checks, err = converter.convert_docx_to_pdf(
        saved_docx_path=docx_file,
        attempt_dir=tmp_path / "attempt",
        expected_draft=draft,
        docx_hash="sha256:" + "0" * 64,
    )

    assert pdf_path is None
    assert err is not None
    assert err.category == ErrorCategory.TRANSIENT_SERVICE
    assert err.details.get("code") == "renderer_failed"
    assert err.details.get("exit_code") == 42


def test_converter_zero_exit_no_output(tmp_path: Path):
    # Fake executable that exits 0 but creates no PDF
    script = tmp_path / "fake_noop.py"
    script.write_text("import sys; sys.exit(0)")

    fake_exe = tmp_path / "fake_noop.bat"
    fake_exe.write_text(f'@"{sys.executable}" "{script}" %*\n')

    settings = RenderingSettings(
        libreoffice_path=fake_exe,
        conversion_timeout_seconds=5,
    )
    converter = LibreOfficeConverter(settings)

    draft = _build_test_draft()
    docx_file = tmp_path / "test.docx"
    docx_file.write_text("dummy")

    pdf_path, checks, err = converter.convert_docx_to_pdf(
        saved_docx_path=docx_file,
        attempt_dir=tmp_path / "attempt",
        expected_draft=draft,
        docx_hash="sha256:" + "0" * 64,
    )

    assert pdf_path is None
    assert err is not None
    assert err.category == ErrorCategory.VALIDATION
    assert err.details.get("code") == "render_output_invalid"

