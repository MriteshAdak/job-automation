"""Tests for title, credential, and organization validation (GEN-04-S03)."""
from __future__ import annotations

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference


def test_altered_title_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "title",
        "source_index": None,
        "text": f"Senior {cand_fact.title}",  # Inflated title!
    })

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "title",
        "original_value": cand_fact.title,
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "title_altered" in codes


def test_credential_role_confusion_is_fatal(setup_validation):
    env = setup_validation()
    role_fact = env.bundle.ordered_facts[0]  # Role/employment fact
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=role_fact.fact_id,
    )

    # Place role fact title into an education section
    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "title",
        "source_index": None,
        "text": role_fact.title,
    })

    # Add education section linking this claim
    new_sections = list(env.draft.sections)
    edu_section = new_sections[0].model_copy(update={
        "section_id": "education",
        "heading_key": "education",
        "claim_ids": [new_claims[0].claim_id],
        "entries": [],
        "subjective_ids": [],
    })
    # Replace sections to have experience and education
    new_sections.append(edu_section)

    headings = dict(env.draft.headings)
    headings["education"] = "Ausbildung"

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "title",
        "original_value": role_fact.title,
    })

    test_draft = env.draft.model_copy(update={
        "sections": new_sections,
        "claims": new_claims,
        "protected_values": bad_pv,
        "headings": headings,
    })

    res = env.validation_service.validate_content(env.request.request_id, test_draft)
    assert res.report is not None
    codes = [i.code for i in res.report.issues]
    assert "credential_role_confusion" in codes

