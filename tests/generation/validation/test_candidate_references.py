"""Tests for candidate evidence resolution and reference verification (GEN-04-S02)."""
from __future__ import annotations

import uuid

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference


def test_nonexistent_fact_id_is_fatal(setup_validation):
    env = setup_validation()
    fake_fact_id = uuid.uuid4()

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            bad_ref = CandidateEvidenceReference(
                source_kind="candidate",
                profile_version=env.snapshot.profile_version,
                fact_id=fake_fact_id,
            )
            c = c.model_copy(update={"evidence_reference": bad_ref})
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={"evidence_reference": new_claims[0].evidence_reference})
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"
    codes = [i.code for i in res.report.issues]
    assert "fact_not_found" in codes


def test_wrong_profile_version_is_fatal(setup_validation):
    env = setup_validation()
    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            bad_ref = CandidateEvidenceReference(
                source_kind="candidate",
                profile_version="v0.0.1-wrong",
                fact_id=c.evidence_reference.fact_id,
            )
            c = c.model_copy(update={"evidence_reference": bad_ref})
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={"evidence_reference": new_claims[0].evidence_reference})
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"
    codes = [i.code for i in res.report.issues]
    assert "wrong_profile_version" in codes


def test_unadmitted_fact_is_fatal(setup_validation):
    # Using RAG where top_k=0 so facts are not admitted
    env = setup_validation(strategy="rag")
    # optional_fact is in profile, but not admitted in RAG top_k=0 bundle!
    unadmitted_fact = env.optional_fact

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            unadmitted_ref = CandidateEvidenceReference(
                source_kind="candidate",
                profile_version=env.snapshot.profile_version,
                fact_id=unadmitted_fact.fact_id,
            )
            c = c.model_copy(update={
                "evidence_reference": unadmitted_ref,
                "text": unadmitted_fact.claims[0],
                "source_field": "claims",
                "source_index": 0,
            })
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={
                "evidence_reference": new_claims[0].evidence_reference,
                "source_field": "claims",
                "original_value": unadmitted_fact.claims,
            })
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "fact_not_admitted" in codes


def test_purpose_unauthorized_fact_is_fatal(setup_validation):
    # cv_only_fact is not authorized for cover_letter
    env = setup_validation(kind="cover_letter")
    cv_fact = env.cv_only_fact

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            bad_ref = CandidateEvidenceReference(
                source_kind="candidate",
                profile_version=env.snapshot.profile_version,
                fact_id=cv_fact.fact_id,
            )
            c = c.model_copy(update={
                "evidence_reference": bad_ref,
                "text": cv_fact.claims[0],
                "source_field": "claims",
                "source_index": 0,
            })
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={
                "evidence_reference": new_claims[0].evidence_reference,
                "source_field": "claims",
                "original_value": cv_fact.claims,
            })
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "fact_purpose_unauthorized" in codes


def test_source_index_out_of_bounds_is_fatal(setup_validation):
    env = setup_validation()
    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate" and c.source_field == "claims":
            c = c.model_copy(update={"source_index": 999})
        new_claims.append(c)

    bad_draft = env.draft.model_copy(update={"claims": new_claims})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "source_index_out_of_bounds" in codes


def test_scalar_field_with_source_index_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            c = c.model_copy(update={
                "source_field": "title",
                "source_index": 0,  # Scalar field must not have source_index!
                "text": cand_fact.title,
            })
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={
                "source_field": "title",
                "original_value": cand_fact.title,
            })
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "unexpected_source_index" in codes

