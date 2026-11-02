"""PDF structure, text extraction, and content verification using pypdf (GEN-05-S04)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pypdf

from job_automation.contracts.draft_content import DraftDocumentV2


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for robust content comparison."""
    return re.sub(r"\s+", " ", text).strip()


def verify_pdf_file(
    pdf_path: Path,
    expected_docx_hash: str,
    expected_draft: DraftDocumentV2,
) -> tuple[bool, dict[str, Any], str | None]:
    """Verify PDF signature, page bounds, parser readability, and content preservation.

    Returns:
        (is_valid, checks_dict, failure_reason)
    """
    checks: dict[str, Any] = {
        "file_exists": False,
        "size_bytes": 0,
        "valid_pdf_signature": False,
        "is_encrypted": False,
        "page_count": 0,
        "pages_have_text": False,
        "headings_covered": False,
        "claims_covered": False,
        "expected_docx_hash": expected_docx_hash,
    }

    if not pdf_path.is_file():
        return False, checks, f"PDF file does not exist: {pdf_path}"

    size = pdf_path.stat().st_size
    checks["size_bytes"] = size
    checks["file_exists"] = True

    if size < 100:
        return False, checks, f"PDF file size too small ({size} bytes, expected >= 100)"
    if size > 50 * 1024 * 1024:
        return False, checks, f"PDF file size exceeds 50MB bound ({size} bytes)"

    # 1. Signature Check
    try:
        with pdf_path.open("rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False, checks, f"Invalid PDF signature header: {header!r}"
            checks["valid_pdf_signature"] = True
    except Exception as exc:
        return False, checks, f"Failed to read PDF signature: {exc}"

    # 2. Parse and Extract Text with pypdf
    try:
        reader = pypdf.PdfReader(str(pdf_path))
        if reader.is_encrypted:
            checks["is_encrypted"] = True
            return False, checks, "Rendered PDF is encrypted; unencrypted readable output required"

        page_count = len(reader.pages)
        checks["page_count"] = page_count
        if page_count < 1:
            return False, checks, "PDF contains 0 pages"
        if page_count > 50:
            return False, checks, f"PDF page count exceeds 50 pages bound ({page_count} pages)"

        extracted_texts = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            extracted_texts.append(page_text)

        checks["pages_have_text"] = any(bool(t.strip()) for t in extracted_texts)
        if not checks["pages_have_text"]:
            return False, checks, "All PDF pages returned empty text on extraction"

    except Exception as exc:
        return False, checks, f"pypdf failed to parse PDF: {exc}"

    full_pdf_text = _normalize_whitespace(" ".join(extracted_texts))

    # 3. Headings Check
    missing_headings = []
    for heading in expected_draft.headings.values():
        norm_h = _normalize_whitespace(heading)
        if norm_h not in full_pdf_text:
            missing_headings.append(heading)
    if missing_headings:
        return False, checks, f"Missing expected headings in PDF: {missing_headings}"
    checks["headings_covered"] = True

    # 4. Claims Coverage (Verify key claim substrings survive in PDF)
    missing_claims = []
    for claim in expected_draft.claims:
        norm_claim = _normalize_whitespace(claim.text)
        # Check first 50 chars of claim to handle potential hyphenation/line break variance in PDF
        check_snippet = norm_claim[:min(len(norm_claim), 50)]
        if check_snippet not in full_pdf_text:
            missing_claims.append(claim.claim_id)
    if missing_claims:
        return False, checks, f"Missing expected claim snippets in PDF: {missing_claims}"
    checks["claims_covered"] = True

    return True, checks, None

