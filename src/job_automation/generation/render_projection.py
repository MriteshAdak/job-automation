"""Exact ordered document projection to DOCX using python-docx (GEN-05-S03)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from job_automation.contracts.draft_content import DraftDocumentV2
from job_automation.contracts.enums import DocumentType
from job_automation.generation.render_records import ApprovedLayout

# XML 1.0 valid character regex: strip invalid control characters
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sanitize_text(text: str) -> str:
    """Strip invalid XML control characters while preserving whitespace and German Unicode."""
    return _INVALID_XML_CHARS.sub("", text)


def add_page_number_to_section(section: Any) -> None:
    """Add dynamic page numbers to section footer."""
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run()
    fldSimple = OxmlElement("w:fldSimple")
    fldSimple.set(qn("w:instr"), "PAGE")
    run._r.append(fldSimple)


def project_draft_to_docx(
    draft: DraftDocumentV2,
    layout: ApprovedLayout,
    output_path: Path,
) -> dict[str, Any]:
    """Construct an editable DOCX file from validated C14 v2 draft and approved layout.

    Returns a projection summary including paragraph and token mappings.
    """
    doc = Document()

    # 1. Page and Margins Setup
    section = doc.sections[0]
    section.page_width = Mm(layout.page_setup.page_width_mm)
    section.page_height = Mm(layout.page_setup.page_height_mm)
    section.top_margin = Mm(layout.page_setup.margin_top_mm)
    section.bottom_margin = Mm(layout.page_setup.margin_bottom_mm)
    section.left_margin = Mm(layout.page_setup.margin_left_mm)
    section.right_margin = Mm(layout.page_setup.margin_right_mm)

    add_page_number_to_section(section)

    # 2. Configure Default Style Typography
    normal_style = doc.styles["Normal"]
    normal_style.font.name = layout.typography.primary_font
    normal_style.font.size = Pt(layout.typography.body_font_size_pt)
    normal_style.paragraph_format.line_spacing = layout.typography.line_spacing
    normal_style.paragraph_format.space_after = Pt(4)

    # 3. Sanitize Document Metadata
    core_props = doc.core_properties
    core_props.author = ""
    core_props.last_modified_by = ""
    core_props.title = ""
    core_props.comments = ""

    is_cv = draft.document_type == DocumentType.CV
    claims_by_id = {c.claim_id: c for c in draft.claims}
    blocks_by_id = {b.block_id: b for b in draft.subjective_blocks}

    mapping_summary: dict[str, Any] = {
        "rendered_claims": [],
        "rendered_blocks": [],
        "rendered_sections": [],
        "paragraph_count": 0,
    }

    # 4. Mandatory Draft & Review Notice Banner
    draft_notice_text = layout.draft_notices.get(
        draft.target_language, "Draft – review before use"
    )
    banner_p = doc.add_paragraph()
    banner_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    banner_run = banner_p.add_run(f"[{draft_notice_text}]")
    banner_run.italic = True
    banner_run.font.size = Pt(layout.typography.small_font_size_pt)
    banner_run.font.color.rgb = RGBColor(120, 120, 120)
    banner_p.paragraph_format.space_after = Pt(12)

    # 5. Header / Candidate Identity Notice
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_after = Pt(6)
    title_run = title_p.add_run(
        "Lebenslauf" if (is_cv and draft.target_language == "de")
        else "Curriculum Vitae" if is_cv
        else "Bewerbungsschreiben" if draft.target_language == "de"
        else "Cover Letter"
    )
    title_run.bold = True
    title_run.font.size = Pt(layout.typography.heading1_font_size_pt)

    # Candidate Name is strictly None in C14 v2 (identity omitted upstream)
    cand_p = doc.add_paragraph()
    cand_p.paragraph_format.space_after = Pt(16)
    id_notice = (
        "[Kandidatenname: Ausstehend – Vor Einreichung prüfen]"
        if draft.target_language == "de"
        else "[Candidate Name: Omitted – Review before submission]"
    )
    cand_run = cand_p.add_run(id_notice)
    cand_run.italic = True
    cand_run.font.size = Pt(layout.typography.body_font_size_pt)
    cand_run.font.color.rgb = RGBColor(90, 90, 90)

    # 6. Ordered Section & Entry Projection
    for s in draft.sections:
        heading_text = draft.headings.get(s.section_id, s.heading_key.title())
        h_p = doc.add_paragraph()
        h_p.paragraph_format.keep_with_next = True
        h_p.paragraph_format.space_before = Pt(12)
        h_p.paragraph_format.space_after = Pt(4)
        h_run = h_p.add_run(sanitize_text(heading_text))
        h_run.bold = True
        h_run.font.size = Pt(layout.typography.heading2_font_size_pt)
        mapping_summary["rendered_sections"].append(s.section_id)

        # Section-level direct claims
        for cid in s.claim_ids:
            claim = claims_by_id[cid]
            p = doc.add_paragraph(style="List Bullet" if is_cv else "Normal")
            p.paragraph_format.space_after = Pt(3)
            p.add_run(sanitize_text(claim.text))
            mapping_summary["rendered_claims"].append(cid)

        # Section-level direct subjective blocks
        for bid in s.subjective_ids:
            block = blocks_by_id[bid]
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(sanitize_text(block.text))
            if is_cv:
                run.italic = True
            mapping_summary["rendered_blocks"].append(bid)

        # Section entries
        for entry in s.entries:
            for cid in entry.claim_ids:
                claim = claims_by_id[cid]
                # In CVs, claims are rendered as bullet items; in letters, as paragraph blocks
                p = doc.add_paragraph(style="List Bullet" if is_cv else "Normal")
                p.paragraph_format.space_after = Pt(3)
                p.add_run(sanitize_text(claim.text))
                mapping_summary["rendered_claims"].append(cid)

            for bid in entry.subjective_ids:
                block = blocks_by_id[bid]
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(6)
                run = p.add_run(sanitize_text(block.text))
                if is_cv:
                    run.italic = True
                mapping_summary["rendered_blocks"].append(bid)

    mapping_summary["paragraph_count"] = len(doc.paragraphs)

    # 7. Save to Destination Path and Close Handles
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    return mapping_summary

