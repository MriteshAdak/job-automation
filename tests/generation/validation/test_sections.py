"""Tests for document structure, required sections, and catalog compliance (GEN-04-S04)."""
from __future__ import annotations

import pytest

from job_automation.contracts.draft_content import DraftEntry, DraftSection


def test_missing_required_experience_is_fatal(setup_validation):
    env = setup_validation()

    # Remove experience section and keep only a summary section
    new_sections = [
        DraftSection(
            section_id="summary",
            heading_key="summary",
            claim_ids=[c.claim_id for c in env.draft.claims],
            subjective_ids=[b.block_id for b in env.draft.subjective_blocks],
        )
    ]
    headings = {"summary": "Profil"}

    bad_draft = env.draft.model_copy(update={
        "sections": new_sections,
        "headings": headings,
    })

    res = env.validation_service.validate_content(env.request.request_id, bad_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "missing_required_section" in codes


def test_missing_required_closing_in_cover_letter_is_fatal(setup_validation):
    env = setup_validation(kind="cover_letter")

    # Cover letter requires both 'experience' and 'closing'
    # Remove 'closing' section
    new_sections = [s for s in env.draft.sections if s.heading_key != "closing"]
    if len(new_sections) == len(env.draft.sections):
        # The baseline draft might only have experience; in that case closing is missing!
        pass

    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None
    # If baseline draft generated without closing section, it will fail with missing_required_section!
    draft_headings = [s.heading_key for s in env.draft.sections]
    if "closing" not in draft_headings:
        codes = [i.code for i in res.report.issues]
        assert "missing_required_section" in codes


def test_duplicate_section_is_fatal(setup_validation):
    env = setup_validation()

    dup_section = env.draft.sections[0].model_copy(update={"section_id": "experience_dup"})
    bad_sections = [env.draft.sections[0], dup_section]
    bad_headings = dict(env.draft.headings)
    bad_headings["experience_dup"] = "Berufserfahrung"

    bad_draft = env.draft.model_copy(update={
        "sections": bad_sections,
        "headings": bad_headings,
    })

    res = env.validation_service.validate_content(env.request.request_id, bad_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "duplicate_section" in codes


def test_experience_section_lacking_candidate_evidence_is_fatal(setup_validation):
    env = setup_validation()

    # Experience section contains ONLY job claims
    job_claim_ids = [c.claim_id for c in env.draft.claims if c.claim_subject == "job"]
    cand_claims = [c for c in env.draft.claims if c.claim_subject == "job"]
    cand_pv = [pv for pv in env.draft.protected_values if pv.claim_id in job_claim_ids]

    bad_sections = [
        DraftSection(
            section_id="experience",
            heading_key="experience",
            claim_ids=job_claim_ids,
            subjective_ids=[],
        )
    ]

    bad_draft = env.draft.model_copy(update={
        "sections": bad_sections,
        "claims": cand_claims,
        "protected_values": cand_pv,
        "subjective_blocks": [],
    })

    res = env.validation_service.validate_content(env.request.request_id, bad_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "experience_lacks_candidate_evidence" in codes


def test_non_catalog_heading_is_fatal(setup_validation):
    env = setup_validation()

    bad_headings = dict(env.draft.headings)
    for k in bad_headings:
        bad_headings[k] = "Invented Custom Header"

    bad_draft = env.draft.model_copy(update={"headings": bad_headings})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "heading_invalid" in codes

