"""Tests for AutomaticRequestPublisher and GEN-01 admission integration."""

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
    SubmissionState,
)
from job_automation.generation.automatic.request_publisher import (
    AutomaticRequestPublisher,
)
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _make_candidate(cand_id: uuid.UUID, job_id: uuid.UUID) -> AutomaticDraftCandidate:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    return AutomaticDraftCandidate(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        assessment_id=uuid.uuid4(),
        assessment_input_fingerprint="sha256:assess_fp",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=85.0,
        score_scale="0-100",
        evaluated_at=now,
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:post_rev",
        normalized_content_hash="sha256:post_norm",
        profile_version="v1.0",
        profile_digest="sha256:prof",
        search_policy_version="v1.0",
        search_policy_hash="sha256:search",
        availability_status=PostingAvailability.ACTIVE,
        availability_observed_at=now,
        candidate_application_state="New",
        candidate_opted_out=False,
        candidate_control_observed_at=now,
        run_id=uuid.uuid4(),
        run_mode="production",
        is_authoritative_selection=True,
    )


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID, company_name: str = "Corp") -> CanonicalJob:
    now = datetime.now(timezone.utc)
    job = CanonicalJob(
        canonical_job_id=job_id,
        company_name=company_name,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now,
        last_seen_at=now,
        availability=PostingAvailability.ACTIVE,
    )
    engine.canonical_jobs.save_canonical_job(job)
    return job


def test_publish_intent_success_and_binding(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Prepopulate canonical job
    _create_canonical_job(engine, job_id, "Acme Corp")

    cand = _make_candidate(cand_id, job_id)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    intent = AutomaticDraftIntent(
        client_request_key="auto02:v1:test_intent_1",
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint="sha256:mat1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest="sha256:digest1",
        request_payload_json="{}",
        submission_state=SubmissionState.RESERVED,
    )
    engine.automatic_drafts.save_intent(intent)

    publisher = AutomaticRequestPublisher(engine)
    req, err = publisher.publish_intent(intent, cand, policy)

    assert err is None
    assert req is not None
    assert req.client_request_key == intent.client_request_key
    assert req.canonical_job_id == job_id
    assert req.state == GenerationProcessing.PENDING

    # Check updated intent state in DB
    updated_intent = engine.automatic_drafts.get_intent(intent.intent_id)
    assert updated_intent is not None
    assert updated_intent.submission_state == SubmissionState.ACKNOWLEDGED
    assert updated_intent.local_request_id == req.request_id

    # Check AutomaticRequestBinding in DB
    binding = engine.automatic_drafts.get_binding_by_request_id(req.request_id)
    assert binding is not None
    assert binding.intent_id == intent.intent_id
    assert binding.expected_assessment_id == cand.assessment_id
    assert binding.expected_posting_revision_hash == cand.posting_revision_hash


def test_sibling_bundle_partial_failure_and_resumption(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Prepopulate canonical job
    _create_canonical_job(engine, job_id, "Acme Corp")

    cand = _make_candidate(cand_id, job_id)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[
            DocumentVariantConfig(document_type=DocumentType.CV),
            DocumentVariantConfig(document_type=DocumentType.COVER_LETTER),
        ],
    )

    intent_cv = AutomaticDraftIntent(
        client_request_key="auto02:v1:bundle_cv",
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint="sha256:mat_cv",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest="sha256:digest_cv",
        request_payload_json="{}",
        submission_state=SubmissionState.RESERVED,
    )
    # Intent letter targeting non-existent canonical job to simulate admission error
    non_existent_job = uuid.uuid4()
    intent_letter = AutomaticDraftIntent(
        client_request_key="auto02:v1:bundle_letter",
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=non_existent_job,
        document_type=DocumentType.COVER_LETTER,
        material_generation_fingerprint="sha256:mat_letter",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest="sha256:digest_letter",
        request_payload_json="{}",
        submission_state=SubmissionState.RESERVED,
    )
    engine.automatic_drafts.save_intent(intent_cv)
    engine.automatic_drafts.save_intent(intent_letter)

    publisher = AutomaticRequestPublisher(engine)
    results = publisher.publish_bundle([intent_cv, intent_letter], cand, policy)

    # First intent (CV) succeeded
    assert results[0][1] is not None
    assert results[0][2] is None
    # Second intent (Letter) failed admission because non_existent_job does not exist
    assert results[1][1] is None
    assert results[1][2] is not None

    # Verify first intent is preserved and ACKNOWLEDGED
    db_cv = engine.automatic_drafts.get_intent(intent_cv.intent_id)
    assert db_cv.submission_state == SubmissionState.ACKNOWLEDGED

    # Second intent is FAILED
    db_letter = engine.automatic_drafts.get_intent(intent_letter.intent_id)
    assert db_letter.submission_state == SubmissionState.FAILED

    # Now create the missing job and retry publication of ONLY the failed intent!
    _create_canonical_job(engine, non_existent_job, "Acme Corp Sibling")

    req2, err2 = publisher.publish_intent(db_letter, cand, policy)
    assert err2 is None
    assert req2 is not None
    assert req2.client_request_key == intent_letter.client_request_key

    # db_cv is still intact and not duplicated!
    cv_reqs = engine.generation_requests.list_by_job(job_id)
    assert len(cv_reqs) == 1
