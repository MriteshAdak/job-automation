"""Tests for AutomaticPreflightGuard at the GEN-01/GEN-02 boundary."""

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
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.automatic.preflight import AutomaticPreflightGuard
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.generation.automatic.records import (
    AutomaticDraftIntent,
    AutomaticDraftPolicy,
    AutomaticRequestBinding,
    SubmissionState,
)
from job_automation.generation.input_records import (
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
)
from job_automation.orchestration.records import AssessmentSelection
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _make_frozen_job(job_id: uuid.UUID, posting_revision_hash: str) -> FrozenJobSnapshot:
    now = datetime.now(timezone.utc)
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id=f"job-{job_id}")
    norm = NormalizedPosting(
        source_key=sk,
        normalizer_version="v1.0",
        raw_reference="ref1",
        raw_content_hash="sha256:" + "0" * 64,
        title="Title",
        company_name_hint="Company",
        observed_at=now,
        description_clean="Description",
        source_url="https://example.com/job",
        application_url="https://example.com/apply",
    )
    return FrozenJobSnapshot(
        canonical_job_id=job_id,
        company_name="Company",
        posting_revision_id=str(uuid.uuid4()),
        posting_revision_hash=posting_revision_hash,
        raw_content_hash="sha256:" + "0" * 64,
        source_key=sk,
        normalized_posting=norm,
        observed_at=now,
        first_seen_at=now,
        last_seen_at=now,
        snapshot_digest="sha256:" + "0" * 64,
    )


def _create_intent(
    engine: StorageEngine,
    intent_id: uuid.UUID,
    client_key: str,
    cand_id: uuid.UUID,
    job_id: uuid.UUID,
) -> AutomaticDraftIntent:
    now = datetime.now(timezone.utc)
    intent = AutomaticDraftIntent(
        intent_id=intent_id,
        client_request_key=client_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint="mat1",
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        decision_id=uuid.uuid4(),
        request_payload_digest="d1",
        request_payload_json="{}",
        submission_state=SubmissionState.RESERVED,
        created_at=now,
        updated_at=now,
    )
    engine.automatic_drafts.save_intent(intent)
    return intent


def test_manual_request_bypasses_guard(tmp_path):
    engine = _setup_engine(tmp_path)
    req = GenerationRequest(
        request_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
    )
    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req)
    assert ok
    assert err is None
    assert receipt is None


def test_automatic_request_rejects_allow_unavailable_override(tmp_path):
    engine = _setup_engine(tmp_path)
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    client_key = "auto02:v1:test_key"

    _create_intent(engine, intent_id, client_key, cand_id, job_id)

    binding = AutomaticRequestBinding(
        local_request_id=req_id,
        intent_id=intent_id,
        client_request_key=client_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        expected_assessment_id=uuid.uuid4(),
        expected_assessment_fingerprint="fp1",
        expected_material_fingerprint="mat1",
        expected_posting_revision_hash="post_hash_1",
        expected_profile_version="prof_v1",
        expected_profile_digest="prof_hash_1",
        expected_search_policy_version="v1.0",
        expected_search_policy_hash="search_hash_1",
    )
    engine.automatic_drafts.save_binding(binding)

    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
        allow_unavailable_job=True,  # Forbidden for automatic requests!
    )

    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req)
    assert not ok
    assert err is not None
    assert "cannot have allow_unavailable_job=True" in err.message


def test_queue_to_freeze_race_posting_changed(tmp_path):
    engine = _setup_engine(tmp_path)
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    assess_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    client_key = "auto02:v1:test_key"

    _create_intent(engine, intent_id, client_key, cand_id, job_id)

    binding = AutomaticRequestBinding(
        local_request_id=req_id,
        intent_id=intent_id,
        client_request_key=client_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        expected_assessment_id=assess_id,
        expected_assessment_fingerprint="fp1",
        expected_material_fingerprint="mat1",
        expected_posting_revision_hash="post_hash_original",
        expected_profile_version="prof_v1",
        expected_profile_digest="prof_hash_1",
        expected_search_policy_version="v1.0",
        expected_search_policy_hash="search_hash_1",
    )
    engine.automatic_drafts.save_binding(binding)

    # Active selection matches expected
    sel = AssessmentSelection(
        canonical_job_id=job_id,
        candidate_id=cand_id,
        purpose="assessment",
        input_fingerprint="fp1",
        assessment_id=assess_id,
        evaluated_at=datetime.now(timezone.utc),
        generation_token="gen_1",
        disposition=AssessmentDisposition.ELIGIBLE,
    )
    engine.pipeline_work.save_assessment_selection(sel)

    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
        allow_unavailable_job=False,
    )

    # Posting changed at freeze time!
    job_snap_changed = _make_frozen_job(job_id, "post_hash_MODIFIED")

    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req, resolved_job=job_snap_changed)
    assert not ok
    assert err is not None
    assert "Posting revision hash changed" in err.message


def test_queue_to_freeze_race_assessment_no_longer_eligible(tmp_path):
    engine = _setup_engine(tmp_path)
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    assess_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    client_key = "auto02:v1:test_key"

    _create_intent(engine, intent_id, client_key, cand_id, job_id)

    binding = AutomaticRequestBinding(
        local_request_id=req_id,
        intent_id=intent_id,
        client_request_key=client_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        expected_assessment_id=assess_id,
        expected_assessment_fingerprint="fp1",
        expected_material_fingerprint="mat1",
        expected_posting_revision_hash="post_hash_1",
        expected_profile_version="prof_v1",
        expected_profile_digest="prof_hash_1",
        expected_search_policy_version="v1.0",
        expected_search_policy_hash="search_hash_1",
    )
    engine.automatic_drafts.save_binding(binding)

    # Active selection was replaced with a REJECTED disposition!
    sel_rejected = AssessmentSelection(
        canonical_job_id=job_id,
        candidate_id=cand_id,
        purpose="assessment",
        input_fingerprint="fp2",
        assessment_id=uuid.uuid4(),
        evaluated_at=datetime.now(timezone.utc),
        generation_token="gen_2",
        disposition=AssessmentDisposition.REJECTED,
    )
    engine.pipeline_work.save_assessment_selection(sel_rejected)

    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
        allow_unavailable_job=False,
    )

    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req)
    assert not ok
    assert err is not None
    assert "Assessment selection changed" in err.message


def test_preflight_success_records_revalidation_receipt(tmp_path):
    engine = _setup_engine(tmp_path)
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    assess_id = uuid.uuid4()
    intent_id = uuid.uuid4()
    client_key = "auto02:v1:test_key"

    _create_intent(engine, intent_id, client_key, cand_id, job_id)

    binding = AutomaticRequestBinding(
        local_request_id=req_id,
        intent_id=intent_id,
        client_request_key=client_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        expected_assessment_id=assess_id,
        expected_assessment_fingerprint="fp1",
        expected_material_fingerprint="mat1",
        expected_posting_revision_hash="post_hash_1",
        expected_profile_version="prof_v1",
        expected_profile_digest="prof_hash_1",
        expected_search_policy_version="v1.0",
        expected_search_policy_hash="search_hash_1",
    )
    engine.automatic_drafts.save_binding(binding)

    sel = AssessmentSelection(
        canonical_job_id=job_id,
        candidate_id=cand_id,
        purpose="assessment",
        input_fingerprint="fp1",
        assessment_id=assess_id,
        evaluated_at=datetime.now(timezone.utc),
        generation_token="gen_1",
        disposition=AssessmentDisposition.ELIGIBLE,
    )
    engine.pipeline_work.save_assessment_selection(sel)

    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
        allow_unavailable_job=False,
    )

    job_snap = _make_frozen_job(job_id, "post_hash_1")

    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req, resolved_job=job_snap)
    assert ok
    assert err is None
    assert receipt is not None
    assert receipt["outcome"] == "verified"

    # Verify receipt persisted in DB binding
    updated_binding = engine.automatic_drafts.get_binding_by_request_id(req_id)
    assert updated_binding.revalidation_receipt is not None
    assert updated_binding.revalidation_receipt["outcome"] == "verified"
