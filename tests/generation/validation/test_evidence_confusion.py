"""Tests for candidate versus job evidence confusion (GEN-04-S02)."""
from __future__ import annotations

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference


def test_candidate_claim_citing_job_evidence_is_fatal(setup_validation):
    env = setup_validation()

    # Candidate claim tries to cite a JobEvidenceReference
    existing_job_claim = next(c for c in env.draft.claims if c.claim_subject == "job")
    job_ref = JobEvidenceReference(
        source_kind="job",
        posting_revision=existing_job_claim.evidence_reference.posting_revision,
        field_path="description_clean",
        quotation="Require Rust.",
    )

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "candidate":
            c = c.model_copy(update={
                "evidence_reference": job_ref,
                "text": "Require Rust.",
                "source_field": "description_clean",
                "source_index": None,
            })
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[0].claim_id:
            pv = pv.model_copy(update={
                "evidence_reference": job_ref,
                "source_field": "description_clean",
                "original_value": "We may offer hybrid working in Berlin. Require Rust.",
            })
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "claim_subject_mismatch" in codes


def test_job_claim_citing_candidate_evidence_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]

    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    new_claims = []
    for c in env.draft.claims:
        if c.claim_subject == "job":
            c = c.model_copy(update={
                "evidence_reference": cand_ref,
                "text": cand_fact.claims[0],
                "source_field": "claims",
                "source_index": 0,
            })
        new_claims.append(c)

    bad_pv = []
    for pv in env.draft.protected_values:
        if pv.claim_id == new_claims[1].claim_id:
            pv = pv.model_copy(update={
                "evidence_reference": cand_ref,
                "source_field": "claims",
                "original_value": cand_fact.claims,
            })
        bad_pv.append(pv)

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "claim_subject_mismatch" in codes

