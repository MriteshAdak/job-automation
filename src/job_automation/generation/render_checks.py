"""DOCX structural, integrity, and content coverage verification (GEN-05-S03)."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from docx import Document

from job_automation.contracts.draft_content import DraftDocumentV2


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for robust content comparison."""
    return re.sub(r"\s+", " ", text).strip()


def verify_docx_file(
    docx_path: Path,
    expected_draft: DraftDocumentV2,
) -> tuple[bool, dict[str, Any], str | None]:
    """Verify structural validity, ZIP integrity, OOXML parts, and exact content coverage of a rendered DOCX.

    Returns:
        (is_valid, checks_dict, failure_reason)
    """
    checks: dict[str, Any] = {
        "file_exists": False,
        "size_bytes": 0,
        "zip_integrity": False,
        "required_parts_present": False,
        "reopened_paragraphs": 0,
        "headings_covered": False,
        "claims_covered": False,
        "subjective_covered": False,
        "no_unsafe_relationships": False,
    }

    if not docx_path.is_file():
        return False, checks, f"File does not exist: {docx_path}"

    size = docx_path.stat().st_size
    checks["size_bytes"] = size
    checks["file_exists"] = True

    if size < 1000:
        return False, checks, f"DOCX file size too small ({size} bytes, expected >= 1000)"
    if size > 50 * 1024 * 1024:
        return False, checks, f"DOCX file size exceeds 50MB bound ({size} bytes)"

    # 1. ZIP Archive Integrity and Part Inspection
    try:
        with zipfile.ZipFile(docx_path, "r") as zf:
            corrupt = zf.testzip()
            if corrupt is not None:
                return False, checks, f"Corrupted ZIP member in DOCX: {corrupt}"
            checks["zip_integrity"] = True

            namelist = set(zf.namelist())
            required_parts = {"word/document.xml", "[Content_Types].xml", "_rels/.rels"}
            missing_parts = required_parts - namelist
            if missing_parts:
                return False, checks, f"Missing required OOXML parts: {missing_parts}"
            checks["required_parts_present"] = True

            # Inspect relationships for unsafe external targets
            if "word/_rels/document.xml.rels" in namelist:
                rels_content = zf.read("word/_rels/document.xml.rels").decode("utf-8", errors="ignore")
                if "TargetMode=\"External\"" in rels_content and ("http://" in rels_content or "https://" in rels_content):
                    return False, checks, "DOCX contains forbidden external hyperlink or relationship targets"
            checks["no_unsafe_relationships"] = True
    except Exception as exc:
        return False, checks, f"ZIP verification failed: {exc}"

    # 2. Reopen and Extract Text with python-docx
    try:
        doc = Document(str(docx_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        checks["reopened_paragraphs"] = len(paragraphs)
        if not paragraphs:
            return False, checks, "Reopened DOCX contains zero non-empty paragraphs"
    except Exception as exc:
        return False, checks, f"Failed to reopen DOCX with python-docx: {exc}"

    full_text_normalized = _normalize_whitespace(" ".join(paragraphs))

    # 3. Headings Coverage
    missing_headings = []
    for heading in expected_draft.headings.values():
        norm_h = _normalize_whitespace(heading)
        if norm_h not in full_text_normalized:
            missing_headings.append(heading)
    if missing_headings:
        return False, checks, f"Missing expected section headings: {missing_headings}"
    checks["headings_covered"] = True

    # 4. Claims Coverage (Verify exact factual excerpts survive)
    missing_claims = []
    for claim in expected_draft.claims:
        norm_claim = _normalize_whitespace(claim.text)
        if norm_claim not in full_text_normalized:
            missing_claims.append(claim.claim_id)
    if missing_claims:
        return False, checks, f"Missing expected claim texts for claim_ids: {missing_claims}"
    checks["claims_covered"] = True

    # 5. Subjective Blocks Coverage
    missing_blocks = []
    for block in expected_draft.subjective_blocks:
        norm_block = _normalize_whitespace(block.text)
        if norm_block not in full_text_normalized:
            missing_blocks.append(block.block_id)
    if missing_blocks:
        return False, checks, f"Missing subjective blocks: {missing_blocks}"
    checks["subjective_covered"] = True

    return True, checks, None

