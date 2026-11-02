"""Tests for DeduplicationManager, repeat policies, and manual request interaction."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.automatic.history import DeduplicationManager
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
    RepeatMode,
    RepeatPolicy,
    SubmissionState,
)
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    engine = StorageEngine(db_path=db_path)
    engine.initialize_schema()
    return engine


def _create_canonical_job(engine: StorageEngine, canonical_job_id: uuid.UUID, company_name: str = "Acme Corp") -> CanonicalJob:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    job = CanonicalJob(
        canonical_job_id=canonical_job_id,
        company_name=company_name,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now,
        last_seen_at=now,
        availability=PostingAvailability.ACTIVE,
    )
    engine.canonical_jobs.save_canonical_job(job)
    return job


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
        posting_revision_hash="sha256:post_rev_1",
        normalized_content_hash="sha256:post_norm_1",
        profile_version="v1.0",
        profile_digest="sha256:prof_1",
        search_policy_version="v1.0",
        search_policy_hash="sha256:search_1",
        availability_status=PostingAvailability.ACTIVE,
        availability_observed_at=now,
        candidate_application_state="New",
        candidate_opted_out=False,
        candidate_control_observed_at=now,
        run_id=uuid.uuid4(),
        run_mode="production",
        is_authoritative_selection=True,
    )


def test_first_run_admitted(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
    )

    dedup = DeduplicationManager(engine)
    res = dedup.check_variant_deduplication(cand, variant, policy)
    assert res.outcome == AutomaticDraftOutcome.ADMITTED
    assert res.client_request_key.startswith("auto02:v1:")


def test_repeat_identical_run_reused(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
    )

    dedup = DeduplicationManager(engine)
    first_res = dedup.check_variant_deduplication(cand, variant, policy)
    assert first_res.outcome == AutomaticDraftOutcome.ADMITTED

    # Persist intent as if admitted
    intent = AutomaticDraftIntent(
        client_request_key=first_res.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint=first_res.material_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest=first_res.payload_digest,
        request_payload_json=first_res.payload_json,
        submission_state=SubmissionState.ACKNOWLEDGED,
    )
    engine.automatic_drafts.save_intent(intent)

    # Next run (e.g. next day, new assessment UUID and different score)
    cand_day2 = cand.model_copy(
        update={
            "assessment_id": uuid.uuid4(),
            "relevance_score": 88.0,
            "evaluated_at": datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc),
        }
    )
    res_day2 = dedup.check_variant_deduplication(cand_day2, variant, policy)
    assert res_day2.outcome == AutomaticDraftOutcome.REUSED
    assert "already_drafted_identical_inputs" in res_day2.reason_codes
    assert res_day2.client_request_key == first_res.client_request_key


def test_historical_input_reversion_reused(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_v1 = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
        repeat_policy=RepeatPolicy(mode=RepeatMode.ON_MATERIAL_CHANGE, cooldown_hours=0),
    )

    dedup = DeduplicationManager(engine)
    res1 = dedup.check_variant_deduplication(cand_v1, variant, policy)

    intent_v1 = AutomaticDraftIntent(
        client_request_key=res1.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id=cand_v1.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint=res1.material_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest=res1.payload_digest,
        request_payload_json=res1.payload_json,
        submission_state=SubmissionState.ACKNOWLEDGED,
        created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )
    engine.automatic_drafts.save_intent(intent_v1)

    # v2 (changed posting)
    cand_v2 = cand_v1.model_copy(update={"normalized_content_hash": "sha256:post_norm_2"})
    res2 = dedup.check_variant_deduplication(cand_v2, variant, policy)
    assert res2.outcome == AutomaticDraftOutcome.ADMITTED

    intent_v2 = AutomaticDraftIntent(
        client_request_key=res2.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id=cand_v2.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint=res2.material_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest=res2.payload_digest,
        request_payload_json=res2.payload_json,
        submission_state=SubmissionState.ACKNOWLEDGED,
        created_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )
    engine.automatic_drafts.save_intent(intent_v2)

    # Revert to v1 posting!
    res_revert = dedup.check_variant_deduplication(cand_v1, variant, policy)
    assert res_revert.outcome == AutomaticDraftOutcome.REUSED
    assert "historical_input_reversion_reused" in res_revert.reason_codes
    assert res_revert.client_request_key == res1.client_request_key


def test_repeat_mode_first_only_suppresses_material_change(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
        repeat_policy=RepeatPolicy(mode=RepeatMode.FIRST_ONLY),
    )

    dedup = DeduplicationManager(engine)
    res = dedup.check_variant_deduplication(cand, variant, policy)

    intent = AutomaticDraftIntent(
        client_request_key=res.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id=cand.salesforce_org_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint=res.material_fingerprint,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_content_hash=policy.policy_content_hash,
        decision_id=uuid.uuid4(),
        request_payload_digest=res.payload_digest,
        request_payload_json=res.payload_json,
        submission_state=SubmissionState.ACKNOWLEDGED,
    )
    engine.automatic_drafts.save_intent(intent)

    # Material change on profile
    cand_changed = cand.model_copy(update={"profile_digest": "sha256:changed_prof"})
    res_changed = dedup.check_variant_deduplication(cand_changed, variant, policy)
    assert res_changed.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "first_only_already_drafted" in res_changed.reason_codes


def test_matching_manual_request_suppression(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    _create_canonical_job(engine, job_id)
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
    )

    # Create matching manual request that was frozen
    manual_req = GenerationRequest(
        request_id=uuid.uuid4(),
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        target_language="de",
        template_id="standard-cv",
        context_strategy=ContextStrategy.JSON,
        state=GenerationProcessing.RUNNING,
        created_at=datetime.now(timezone.utc),
        claimed_at=datetime.now(timezone.utc),
        frozen_input_versions=FrozenInputVersions(
            posting_revision=cand.posting_revision_hash,
            profile_version=cand.profile_version,
            policy_version="v1.0",
            template_version="v1.0",
        ),
    )
    engine.generation_requests.create_request(manual_req)

    dedup = DeduplicationManager(engine)
    res = dedup.check_variant_deduplication(cand, variant, policy)
    assert res.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "matching_manual_request_exists" in res.reason_codes
    assert res.existing_request_id == manual_req.request_id


def test_ambiguous_pending_manual_request_holds(tmp_path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    _create_canonical_job(engine, job_id)
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
    )

    # Unclaimed pending manual request (no frozen inputs yet)
    manual_req = GenerationRequest(
        request_id=uuid.uuid4(),
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        state=GenerationProcessing.PENDING,
        created_at=datetime.now(timezone.utc),
        template_id="standard-cv",
    )
    engine.generation_requests.create_request(manual_req)

    dedup = DeduplicationManager(engine)
    res = dedup.check_variant_deduplication(cand, variant, policy)
    assert res.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "ambiguous_pending_manual_request" in res.reason_codes
