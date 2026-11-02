"""Tests for BudgetManager volume limits, quotas, and candidate ranking."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    DocumentType,
    PostingAvailability,
)
from job_automation.generation.automatic.budgets import BudgetManager
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
    AutomaticDraftPolicy,
    AutomaticDraftReservation,
    AutomaticVolumeLimits,
    DocumentVariantConfig,
    ReservationStatus,
    SubmissionState,
)
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _make_candidate(cand_id: uuid.UUID, score: float, job_id: uuid.UUID | None = None) -> AutomaticDraftCandidate:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    return AutomaticDraftCandidate(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id or uuid.uuid4(),
        assessment_id=uuid.uuid4(),
        assessment_input_fingerprint="sha256:fp",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=score,
        score_scale="0-100",
        evaluated_at=now,
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:rev",
        normalized_content_hash="sha256:norm",
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


def test_candidate_ranking():
    cand_id = uuid.uuid4()
    job1 = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    job2 = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    job3 = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    c1 = _make_candidate(cand_id, score=80.0, job_id=job1)
    c2 = _make_candidate(cand_id, score=95.0, job_id=job2)
    c3 = _make_candidate(cand_id, score=80.0, job_id=job3)

    bm = BudgetManager(None)  # type: ignore
    ranked = bm.rank_candidates([c1, c2, c3])

    # c2 has highest score 95.0 -> 1st
    assert ranked[0].canonical_job_id == job2
    # c1 and c3 tie at 80.0 -> job1 ("aaaa...") precedes job3 ("cccc...")
    assert ranked[1].canonical_job_id == job1
    assert ranked[2].canonical_job_id == job3


def test_per_run_limit_and_bundle_atomicity(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    cand = _make_candidate(cand_id, score=85.0)
    run_id = uuid.uuid4()

    # Policy allows max 2 requests per run
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        volume_limits=AutomaticVolumeLimits(max_requests_per_run=2),
        document_variants=[
            DocumentVariantConfig(document_type=DocumentType.CV),
            DocumentVariantConfig(document_type=DocumentType.COVER_LETTER),
        ],
    )

    bm = BudgetManager(engine)

    # First bundle of 2 units (CV + Letter) -> passes!
    q1 = bm.check_bundle_quota(cand, policy, bundle_units=2, evaluation_run_id=run_id)
    assert q1.allowed

    # Simulate reserving 1 unit in this run
    intent1 = AutomaticDraftIntent(
        client_request_key="auto02:v1:test1",
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=cand.canonical_job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint="sha256:mat1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest="sha256:pay1",
        request_payload_json="{}",
        submission_state=SubmissionState.ACKNOWLEDGED,
    )
    engine.automatic_drafts.save_intent(intent1)

    res1 = AutomaticDraftReservation(
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=cand.canonical_job_id,
        evaluation_run_id=run_id,
        intent_id=intent1.intent_id,
        client_request_key=intent1.client_request_key,
        document_units=1,
        status=ReservationStatus.ACTIVE,
    )
    engine.automatic_drafts.save_reservation(res1)

    # Now 1 unit is used out of 2.
    # Next candidate needs 2 units (CV + Letter). 1 + 2 = 3 > 2 -> Bundle must be deferred!
    cand2 = _make_candidate(cand_id, score=82.0)
    q2 = bm.check_bundle_quota(cand2, policy, bundle_units=2, evaluation_run_id=run_id)
    assert not q2.allowed
    assert "Per-run limit exceeded" in q2.reason


def test_rolling_window_limit(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    cand = _make_candidate(cand_id, score=85.0)
    run_id = uuid.uuid4()
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)

    # Max 2 in 24 hours
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        volume_limits=AutomaticVolumeLimits(max_requests_per_window=2, window_hours=24.0),
    )
    bm = BudgetManager(engine)

    # Insert 2 reservations 10 hours ago
    for idx in range(2):
        intent = AutomaticDraftIntent(
            client_request_key=f"auto02:v1:win_{idx}",
            candidate_id=cand_id,
            salesforce_org_id=cand.salesforce_org_id,
            canonical_job_id=uuid.uuid4(),
            document_type=DocumentType.CV,
            material_generation_fingerprint=f"sha256:mat_{idx}",
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_content_hash=policy.policy_content_hash,
            decision_id=uuid.uuid4(),
            request_payload_digest=f"sha256:pay_{idx}",
            request_payload_json="{}",
            submission_state=SubmissionState.ACKNOWLEDGED,
        )
        engine.automatic_drafts.save_intent(intent)
        res = AutomaticDraftReservation(
            candidate_id=cand_id,
            salesforce_org_id=cand.salesforce_org_id,
            canonical_job_id=intent.canonical_job_id,
            evaluation_run_id=uuid.uuid4(),
            intent_id=intent.intent_id,
            client_request_key=intent.client_request_key,
            document_units=1,
            status=ReservationStatus.ACTIVE,
            reserved_at=now - timedelta(hours=10),
        )
        engine.automatic_drafts.save_reservation(res)

    # Window count is 2. Attempting to add 1 unit exceeds limit!
    q = bm.check_bundle_quota(cand, policy, bundle_units=1, evaluation_run_id=run_id, now=now)
    assert not q.allowed
    assert "Rolling window limit exceeded" in q.reason

    # But 25 hours later, the older reservations roll out of the window!
    later = now + timedelta(hours=15)
    q_later = bm.check_bundle_quota(cand, policy, bundle_units=1, evaluation_run_id=run_id, now=later)
    assert q_later.allowed

