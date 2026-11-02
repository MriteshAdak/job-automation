"""Headless LibreOffice DOCX-to-PDF converter with isolated profiles (GEN-05-S04)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.pdf_checks import verify_pdf_file
from job_automation.generation.render_process import run_bounded_process
from job_automation.generation.render_settings import RenderingSettings

logger = logging.getLogger(__name__)

DEFAULT_LIBREOFFICE_PATHS = [
    Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
    Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
]


def find_libreoffice_executable(configured_path: Path | None = None) -> Path | None:
    """Resolve an existing LibreOffice soffice.com console executable."""
    if configured_path is not None and configured_path.is_file():
        return configured_path
    for p in DEFAULT_LIBREOFFICE_PATHS:
        if p.is_file():
            return p
    return None


class LibreOfficeConverter:
    """Converts DOCX documents to PDF using headless LibreOffice in an isolated user profile."""

    def __init__(self, settings: RenderingSettings | None = None) -> None:
        self.settings = settings or RenderingSettings()

    def convert_docx_to_pdf(
        self,
        saved_docx_path: Path,
        attempt_dir: Path,
        expected_draft: DraftDocumentV2,
        docx_hash: str,
    ) -> tuple[Path | None, dict[str, Any] | None, ClassifiedError | None]:
        """Convert a saved DOCX file to PDF in an isolated environment.

        Guarantees:
        - Bounded execution with timeout.
        - Isolated user profile via Path.as_uri().
        - Fresh attempt output directory.
        - Independent PDF verification before returning success.
        - Preserves input DOCX on failure.
        """
        executable = find_libreoffice_executable(self.settings.libreoffice_path)
        if executable is None:
            return None, None, ClassifiedError.from_category(
                category=ErrorCategory.MISSING_CONFIGURATION,
                message=(
                    "LibreOffice executable (soffice.com) not found on host machine. "
                    "Install LibreOffice and ensure soffice.com is configured for PDF conversion."
                ),
                details={"code": "renderer_missing"},
            )

        # Attempt isolation
        profile_dir = attempt_dir / "profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        out_dir = attempt_dir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)

        profile_uri = profile_dir.resolve().as_uri()

        cmd = [
            str(executable),
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(out_dir),
            str(saved_docx_path),
        ]

        logger.info("Executing LibreOffice PDF conversion in %s", attempt_dir)
        exit_code, stdout, stderr, timed_out = run_bounded_process(
            cmd,
            cwd=attempt_dir,
            timeout_seconds=self.settings.conversion_timeout_seconds,
            cleanup_grace_seconds=self.settings.cleanup_grace_seconds,
        )

        if timed_out:
            logger.error("LibreOffice conversion timed out after %s seconds", self.settings.conversion_timeout_seconds)
            return None, None, ClassifiedError.from_category(
                category=ErrorCategory.TRANSIENT_SERVICE,
                message=f"LibreOffice conversion timed out after {self.settings.conversion_timeout_seconds} seconds",
                details={"code": "renderer_timeout", "timeout_seconds": self.settings.conversion_timeout_seconds},
            )

        if exit_code != 0:
            redacted_err = (stderr or stdout).strip()[:500]
            logger.error("LibreOffice exited with code %s: %s", exit_code, redacted_err)
            return None, None, ClassifiedError.from_category(
                category=ErrorCategory.TRANSIENT_SERVICE,
                message=f"LibreOffice conversion failed with exit code {exit_code}",
                details={"code": "renderer_failed", "exit_code": exit_code, "diagnostics": redacted_err},
            )

        # Expected output filename matches docx stem
        expected_pdf_path = out_dir / f"{saved_docx_path.stem}.pdf"
        if not expected_pdf_path.is_file():
            logger.error("LibreOffice returned 0 but expected PDF %s was not found", expected_pdf_path)
            return None, None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message="LibreOffice completed with exit code 0 but produced no output PDF file",
                details={"code": "render_output_invalid"},
            )

        # Verify output PDF
        valid, checks, failure_reason = verify_pdf_file(
            expected_pdf_path,
            expected_docx_hash=docx_hash,
            expected_draft=expected_draft,
        )
        if not valid or failure_reason:
            logger.error("Rendered PDF validation failed for %s: %s", expected_pdf_path, failure_reason)
            return None, None, ClassifiedError.from_category(
                category=ErrorCategory.VALIDATION,
                message=f"Rendered PDF output invalid: {failure_reason}",
                details={"code": "render_output_invalid", "checks": checks},
            )

        return expected_pdf_path, checks, None

