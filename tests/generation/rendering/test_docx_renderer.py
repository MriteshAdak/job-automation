"""Unit and integration tests for DOCX generation, German characters, and output verification (GEN-05-S03)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.draft_content import (
    DraftClaim,
    DraftDocumentV2,
    DraftEntry,
    DraftProvenance,
    DraftSection,
    ProtectedSourceValue,
    SubjectiveBlock,
)
from job_automation.contracts.enums import DocumentType
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.contracts.generation import FrozenInputVersions
from job_automation.generation.docx_renderer import DocxRenderer
from job_automation.generation.layout_catalog import LAYOUT_CV_BASIC_A4, LAYOUT_LETTER_BASIC_A4
from job_automation.generation.render_checks import verify_docx_file


def _build_test_draft(
    doc_type: DocumentType = DocumentType.CV,
    language: str = "de",
    claims_text: list[str] | None = None,
    request_id: uuid.UUID | None = None,
) -> DraftDocumentV2:
    req_id = request_id or uuid.uuid4()
    draft_id = uuid.uuid4()
    call_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    fact_id = uuid.uuid4()

    now_utc = datetime.now(timezone.utc)
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version="v2026.1",
        fact_id=fact_id,
    )

    texts = claims_text or [
        "Herr Dr. Müller wohnhaft in der Teststraße 42, Größe: Standard, Prüfung bestanden.",
        "Erreichte eine Umsatzsteigerung von bis zu 20 % im Zeitraum 2021-03 bis 2023-08.",
        "Spezialkenntnisse: äöü ÄÖÜ ß, Währungszeichen € und Anführungszeichen „Erfolg“ sowie Gedankenstrich –.",
    ]

    claims = []
    pv = []
    claim_ids = []
    for i, t in enumerate(texts):
        cid = f"claim_{i}"
        claim_ids.append(cid)
        c = DraftClaim(
            claim_id=cid,
            claim_subject="candidate",
            text=t,
            evidence_reference=cand_ref,
            source_field="claims",
            source_index=i,
        )
        claims.append(c)
        pv.append(
            ProtectedSourceValue(
                claim_id=cid,
                source_field="claims",
                original_value=t,
                evidence_reference=cand_ref,
            )
        )

    sections = [
        DraftSection(
            section_id="experience",
            heading_key="experience",
            claim_ids=claim_ids,
            subjective_ids=["subj_1"],
            entries=[
                DraftEntry(
                    entry_id="entry_1",
                    claim_ids=[],
                    subjective_ids=[],
                )
            ] if False else [],
        )
    ]
    # Update section to have entry containing the claims
    sections = [
        DraftSection(
            section_id="experience",
            heading_key="experience",
            claim_ids=[],
            subjective_ids=[],
            entries=[
                DraftEntry(
                    entry_id="entry_1",
                    claim_ids=claim_ids,
                    subjective_ids=["subj_1"],
                )
            ],
        )
    ]

    subj = [
        SubjectiveBlock(
            block_id="subj_1",
            text="Sehr motiviert für anspruchsvolle Aufgaben in einem agilen Team.",
        )
    ]

    headings = {
        "experience": "Berufserfahrung" if language == "de" else "Work Experience",
    }

    return DraftDocumentV2(
        draft_id=draft_id,
        request_id=req_id,
        document_type=doc_type,
        document_version="draft:1",
        target_language=language,
        template_id="content-basic",
        template_version="1.0",
        template_content_digest="sha256:" + "0" * 64,
        headings=headings,
        candidate_name=None,
        sections=sections,
        claims=claims,
        subjective_blocks=subj,
        protected_values=pv,
        review_issues=[],
        frozen_inputs=FrozenInputVersions(
            posting_revision="sha256:" + "1" * 64,
            profile_version="v2026.1",
            policy_version="pol1",
            template_version="1.0",
        ),
        provenance=DraftProvenance(
            seal_id=f"seal:{req_id}",
            seal_hash="sha256:" + "2" * 64,
            binding_hash="sha256:" + "3" * 64,
            context_receipt_id=uuid.uuid4(),
            context_hash="sha256:" + "4" * 64,
            recipe_hash="sha256:" + "5" * 64,
            prompt_version="1.0",
            schema_id="draft-content-proposal-1.0",
            schema_digest="sha256:" + "6" * 64,
            input_fingerprint="sha256:" + "7" * 64,
            model_identifier="test-model",
            model_digest="sha256:" + "8" * 64,
            model_call_ref=call_id,
            receipt_id=receipt_id,
        ),
    )


def test_docx_rendering_german_unicode(tmp_path: Path):
    draft = _build_test_draft(DocumentType.CV, "de")
    renderer = DocxRenderer()
    out_docx = tmp_path / "test_cv.docx"

    checks, err = renderer.render_docx(draft, LAYOUT_CV_BASIC_A4, out_docx)
    assert err is None
    assert checks is not None
    assert out_docx.is_file()
    assert checks["file_exists"] is True
    assert checks["zip_integrity"] is True
    assert checks["headings_covered"] is True
    assert checks["claims_covered"] is True
    assert checks["subjective_covered"] is True


def test_docx_rendering_long_content_multi_page(tmp_path: Path):
    # Test a 1200-char German bullet and a near-limit claim
    long_bullet = (
        "Leitung der agilen Softwareentwicklung für verteilte Microservices-Architekturen "
        "mit kontinuierlicher Integration und automatisierter Bereitstellung. "
    ) * 8  # ~1200 characters

    near_limit_claim = (
        "Verantwortung für die vollständige Neukonzeption und Migration von Altsystemen "
        "in eine hochverfügbare Multi-Cloud-Infrastruktur unter Einhaltung strenger Sicherheitsstandards. "
    ) * 20  # ~2400 characters

    long_texts = [long_bullet, near_limit_claim] + [f"Reguläre Leistungskennzahl Nummer {i}" for i in range(15)]
    draft = _build_test_draft(DocumentType.CV, "de", claims_text=long_texts)

    renderer = DocxRenderer()
    out_docx = tmp_path / "long_cv.docx"

    checks, err = renderer.render_docx(draft, LAYOUT_CV_BASIC_A4, out_docx)
    assert err is None
    assert checks is not None
    assert out_docx.is_file()
    assert checks["claims_covered"] is True
    assert checks["reopened_paragraphs"] >= len(long_texts)


def test_docx_rendering_safe_text_escaping(tmp_path: Path):
    # Test HTML-like tags, special chars &, <, >, URLs, tabs, and newlines
    hostile_claim = (
        "Kandidat beherrscht <script>alert('xss')</script> & <b>HTML</b>; "
        "besucht https://example.com/job?id=123&lang=de; verwendet Tabulatoren\tund Zeilenumbrüche."
    )
    draft = _build_test_draft(DocumentType.CV, "de", claims_text=[hostile_claim])

    renderer = DocxRenderer()
    out_docx = tmp_path / "safe_cv.docx"

    checks, err = renderer.render_docx(draft, LAYOUT_CV_BASIC_A4, out_docx)
    assert err is None
    assert checks is not None
    assert out_docx.is_file()
    assert checks["claims_covered"] is True
    assert checks["no_unsafe_relationships"] is True


def test_docx_corrupted_file_detected(tmp_path: Path):
    draft = _build_test_draft()
    bad_docx = tmp_path / "corrupt.docx"
    bad_docx.write_bytes(b"PK\x03\x04not-a-valid-docx-archive-just-garbage")

    valid, checks, failure = verify_docx_file(bad_docx, draft)
    assert valid is False
    assert failure is not None
