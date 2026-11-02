"""Tests for internal consistency and entity attribution (GEN-04-S04)."""
from __future__ import annotations

import uuid

import pytest

from job_automation.contracts.draft_content import DraftEntry, DraftSection
from job_automation.contracts.evidence import CandidateEvidenceReference


def test_inconsistent_entry_attribution_is_fatal(setup_validation):
    env = setup_validation()
    facts = env.bundle.ordered_facts
    if len(facts) < 2:
        pytest.skip("Requires at least two candidate facts")

    fact1, fact2 = facts[0], facts[1]
    ref1 = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=fact1.fact_id,
    )
    ref2 = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=fact2.fact_id,
    )

    claim1 = env.draft.claims[0].model_copy(update={
        "claim_id": "c1",
        "evidence_reference": ref1,
        "source_field": "title",
        "source_index": None,
        "text": fact1.title,
    })
    claim2 = env.draft.claims[0].model_copy(update={
        "claim_id": "c2",
        "evidence_reference": ref2,
        "source_field": "title",
        "source_index": None,
        "text": fact2.title,
    })

    pv1 = env.draft.protected_values[0].model_copy(update={
        "claim_id": "c1",
        "evidence_reference": ref1,
        "source_field": "title",
        "original_value": fact1.title,
    })
    pv2 = env.draft.protected_values[0].model_copy(update={
        "claim_id": "c2",
        "evidence_reference": ref2,
        "source_field": "title",
        "original_value": fact2.title,
    })

    # Put both into a single DraftEntry in experience section
    mixed_entry = DraftEntry(entry_id="mixed_role", claim_ids=["c1", "c2"])
    mixed_section = DraftSection(
        section_id="experience",
        heading_key="experience",
        claim_ids=[],
        entries=[mixed_entry],
    )

    test_draft = env.draft.model_copy(update={
        "sections": [mixed_section],
        "claims": [claim1, claim2],
        "protected_values": [pv1, pv2],
        "subjective_blocks": [],
    })

    res = env.validation_service.validate_content(env.request.request_id, test_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "inconsistent_entry_attribution" in codes


def test_internal_title_conflict_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    # Two claims citing the same fact's title but having different text
    claim1 = env.draft.claims[0].model_copy(update={
        "claim_id": "c1",
        "evidence_reference": cand_ref,
        "source_field": "title",
        "source_index": None,
        "text": cand_fact.title,
    })
    claim2 = env.draft.claims[0].model_copy(update={
        "claim_id": "c2",
        "evidence_reference": cand_ref,
        "source_field": "title",
        "source_index": None,
        "text": f"Different {cand_fact.title}",
    })

    source_map = {
        "claims": {
            "c1": {"subject": "candidate", "fact": cand_fact, "field": "title"},
            "c2": {"subject": "candidate", "fact": cand_fact, "field": "title"},
        },
        "facts_by_id": {cand_fact.fact_id: cand_fact},
    }

    from job_automation.generation.validation_consistency import validate_internal_consistency
    test_draft = env.draft.model_copy(update={"claims": [claim1, claim2]})
    issues = validate_internal_consistency(test_draft, source_map)

    codes = [i.code for i in issues]
    assert "internal_title_conflict" in codes

