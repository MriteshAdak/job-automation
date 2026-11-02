"""Tests for decision-input fingerprints, material generation fingerprints, and client request keys."""

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    DocumentType,
    PostingAvailability,
)
from job_automation.generation.automatic.fingerprints import (
    compute_decision_input_fingerprint,
    compute_material_generation_fingerprint,
    compute_payload_digest,
    derive_automatic_client_request_key,
)
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
)


def _make_candidate() -> AutomaticDraftCandidate:
    return AutomaticDraftCandidate(
        candidate_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        assessment_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        assessment_input_fingerprint="sha256:assess123",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=85.0,
        score_scale="0-100",
        evaluated_at=datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:postrev123",
        normalized_content_hash="sha256:normpost123",
        profile_version="v1.0",
        profile_digest="sha256:prof123",
        search_policy_version="v1.0",
        search_policy_hash="sha256:search123",
        availability_status=PostingAvailability.ACTIVE,
        availability_observed_at=datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        candidate_application_state="New",
        candidate_opted_out=False,
        candidate_control_observed_at=datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
        run_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        run_mode="production",
        is_authoritative_selection=True,
    )


def test_decision_fingerprint_invariance_and_sensitivity():
    cand = _make_candidate()
    policy = AutomaticDraftPolicy(
        candidate_id=cand.candidate_id,
        salesforce_org_id=cand.salesforce_org_id,
    )

    f1 = compute_decision_input_fingerprint(cand, policy)

    # Invariant to run_id changes
    cand_diff_run = cand.model_copy(update={"run_id": uuid.uuid4()})
    assert compute_decision_input_fingerprint(cand_diff_run, policy) == f1

    # Sensitive to relevance_score change
    cand_diff_score = cand.model_copy(update={"relevance_score": 90.0})
    assert compute_decision_input_fingerprint(cand_diff_score, policy) != f1

    # Sensitive to posting_revision_hash change
    cand_diff_rev = cand.model_copy(update={"posting_revision_hash": "sha256:changed"})
    assert compute_decision_input_fingerprint(cand_diff_rev, policy) != f1

    # Sensitive to policy version change
    policy_diff_v = policy.model_copy(update={"policy_version": "v2.0", "policy_content_hash": "changed"})
    assert compute_decision_input_fingerprint(cand, policy_diff_v) != f1


def test_material_generation_fingerprint_invariance_and_sensitivity():
    cand = _make_candidate()
    variant = DocumentVariantConfig(
        document_type=DocumentType.CV,
        target_language="de",
        template_id="standard-cv",
        context_strategy=ContextStrategy.JSON,
        formats=["docx", "pdf"],
    )

    m1 = compute_material_generation_fingerprint(cand, variant)

    # Invariant to assessment UUID or relevance score
    cand_new_assess = cand.model_copy(
        update={
            "assessment_id": uuid.uuid4(),
            "relevance_score": 99.0,
            "evaluated_at": datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
        }
    )
    assert compute_material_generation_fingerprint(cand_new_assess, variant) == m1

    # Sensitive to candidate profile digest
    cand_new_prof = cand.model_copy(update={"profile_digest": "sha256:changed_prof"})
    assert compute_material_generation_fingerprint(cand_new_prof, variant) != m1

    # Sensitive to normalized job posting content
    cand_new_post = cand.model_copy(update={"normalized_content_hash": "sha256:changed_job"})
    assert compute_material_generation_fingerprint(cand_new_post, variant) != m1

    # Sensitive to target language or document type
    variant_en = variant.model_copy(update={"target_language": "en"})
    assert compute_material_generation_fingerprint(cand, variant_en) != m1


def test_client_request_key_grammar_and_policy_version_independence():
    cand = _make_candidate()
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    mat = compute_material_generation_fingerprint(cand, variant)

    key1 = derive_automatic_client_request_key(
        material_fingerprint=mat,
        org_id=cand.salesforce_org_id,
        candidate_id=cand.candidate_id,
        canonical_job_id=cand.canonical_job_id,
        document_type=variant.document_type.value,
    )

    assert key1.startswith("auto02:v1:")
    assert len(key1) <= 60

    # Changing policy version has NO effect on client request key
    key2 = derive_automatic_client_request_key(
        material_fingerprint=mat,
        org_id=cand.salesforce_org_id,
        candidate_id=cand.candidate_id,
        canonical_job_id=cand.canonical_job_id,
        document_type=variant.document_type.value,
    )
    assert key1 == key2

