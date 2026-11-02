"""Tests for metric extraction, alteration detection, and transplantation (GEN-04-S03)."""
from __future__ import annotations

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference


def test_altered_candidate_metric_is_fatal(setup_validation):
    env = setup_validation()
    fact_with_metric = None
    for f in env.bundle.ordered_facts:
        if getattr(f, "metrics", None):
            fact_with_metric = f
            break
    if not fact_with_metric:
        fact_with_metric = env.bundle.ordered_facts[0].model_copy(update={"metrics": ["40% latency reduction"]})

    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=fact_with_metric.fact_id,
    )

    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "metrics",
        "source_index": 0,
        "text": "80% latency reduction",  # Altered from 40%!
    })

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "metrics",
        "original_value": fact_with_metric.metrics,
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "metric_value_altered" in codes


def test_ungrounded_metric_in_claim_text_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    # Claim text has "40% cost savings" but source_field is "claims" and original text does not have "40%"
    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "claims",
        "source_index": 0,
        "text": "Achieved 40% cost savings through migration",  # Contains ungrounded quantitative metric!
    })

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "claims",
        "original_value": cand_fact.claims,
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "metric_binding_missing" in codes


def test_quantitative_claim_in_subjective_block_is_fatal(setup_validation):
    env = setup_validation()

    # Model tries to hide a quantitative claim in subjective blocks
    bad_blocks = list(env.draft.subjective_blocks)
    bad_blocks[0] = bad_blocks[0].model_copy(update={
        "text": "I can deliver 50% revenue growth in this role."
    })

    bad_draft = env.draft.model_copy(update={"subjective_blocks": bad_blocks})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "metric_binding_missing" in codes or "subjective_text_invalid" in codes

