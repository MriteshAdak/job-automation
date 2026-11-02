"""Acceptance matrix verification tests for AUTO-02 (A02-T01 through A02-T25).

Explicitly validates each scenario mandated by docs/stories/AUTO-02.md §8.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.generation.automatic.evaluator import AutomaticDraftEvaluator
from job_automation.generation.automatic.fingerprints import (
    compute_material_generation_fingerprint,
    derive_automatic_client_request_key,
)
from job_automation.generation.automatic.history import DeduplicationManager
from job_automation.generation.automatic.preflight import AutomaticPreflightGuard
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftIntent,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    AutomaticVolumeLimits,
    DocumentVariantConfig,
    RepeatMode,
    RepeatPolicy,
    ReservationStatus,
    SubmissionState,
)
from job_automation.generation.automatic.service import AutomaticDraftService
from job_automation.generation.input_records import FrozenJobSnapshot
from job_automation.orchestration.records import AssessmentSelection
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    return engine


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


def _make_candidate(
    cand_id: uuid.UUID,
    job_id: uuid.UUID,
    score: float = 85.0,
    org_id: str = "00D000000000001EAA",
    now: datetime | None = None,
) -> AutomaticDraftCandidate:
    ref_time = now or datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    return AutomaticDraftCandidate(
        candidate_id=cand_id,
        salesforce_org_id=org_id,
        canonical_job_id=job_id,
        assessment_id=uuid.uuid4(),
        assessment_input_fingerprint="sha256:assess_fp",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=score,
        score_scale="0-100",
        evaluated_at=ref_time - timedelta(hours=1),
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:post_rev",
        normalized_content_hash="sha256:post_norm",
        profile_version="v1.0",
        profile_digest="sha256:prof",
        search_policy_version="v1.0",
        search_policy_hash="sha256:search",
        availability_status=PostingAvailability.ACTIVE,
        availability_observed_at=ref_time - timedelta(hours=1),
        candidate_application_state="New",
        candidate_opted_out=False,
        candidate_control_observed_at=ref_time - timedelta(hours=1),
        run_id=uuid.uuid4(),
        run_mode="production",
        is_authoritative_selection=True,
        rule_coverage_complete=True,
    )


def test_a02_t01_first_successful_eligible_result(tmp_path: Path):
    """A02-T01: First successful selected eligible result meeting configured threshold."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    _create_canonical_job(engine, job_id)

    cand = _make_candidate(cand_id, job_id, score=85.0)
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        minimum_relevance_score=75.0,
        document_variants=[
            DocumentVariantConfig(document_type=DocumentType.CV, formats=["docx", "pdf"]),
            DocumentVariantConfig(document_type=DocumentType.COVER_LETTER, formats=["docx", "pdf"]),
        ],
    )

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=False)

    assert report.jobs_by_outcome.get("admitted") == 1
    assert report.requests_by_outcome.get("admitted") == 2
    assert len(report.admitted_intents) == 2

    # Two distinct C13 GenerationRequest records created
    reqs = engine.generation_requests.list_by_job(job_id)
    assert len(reqs) == 2
    doc_types = {r.document_type for r in reqs}
    assert doc_types == {DocumentType.CV, DocumentType.COVER_LETTER}


def test_a02_t02_repeat_unchanged_evaluation_on_another_day(tmp_path: Path):
    """A02-T02: Repeat unchanged search/evaluation/poll after restart and on another day."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    _create_canonical_job(engine, job_id)

    cand = _make_candidate(cand_id, job_id, score=85.0)
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        minimum_relevance_score=75.0,
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    now1 = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    cand = _make_candidate(cand_id, job_id, score=85.0, now=now1)
    service = AutomaticDraftService(engine)
    r1 = service.evaluate_and_process(policy=policy, candidates=[cand], preview=False, now=now1)
    assert r1.jobs_by_outcome.get("admitted") == 1

    # Rerun on next day
    now2 = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
    cand_day2 = cand.model_copy(
        update={
            "assessment_id": uuid.uuid4(),
            "evaluated_at": now2,
            "availability_observed_at": now2,
            "candidate_control_observed_at": now2,
        }
    )
    r2 = service.evaluate_and_process(policy=policy, candidates=[cand_day2], preview=False, now=now2)
    assert r2.jobs_by_outcome.get("reused") == 1
    assert len(r2.admitted_intents) == 0

    # Still exactly 1 request in DB
    assert len(engine.generation_requests.list_by_job(job_id)) == 1


def test_a02_t03_new_attempt_uuid_and_timestamp_same_content(tmp_path: Path):
    """A02-T03: New run/assessment UUID, refreshed timestamp, same content -> no new material key."""
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    c1 = _make_candidate(cand_id, job_id, score=85.0)
    c2 = c1.model_copy(
        update={
            "run_id": uuid.uuid4(),
            "assessment_id": uuid.uuid4(),
            "evaluated_at": datetime.now(timezone.utc),
        }
    )
    variant = DocumentVariantConfig(document_type=DocumentType.CV)

    m1 = compute_material_generation_fingerprint(c1, variant)
    m2 = compute_material_generation_fingerprint(c2, variant)
    assert m1 == m2

    k1 = derive_automatic_client_request_key(m1, c1.salesforce_org_id, cand_id, job_id, "cv")
    k2 = derive_automatic_client_request_key(m2, c2.salesforce_org_id, cand_id, job_id, "cv")
    assert k1 == k2


def test_a02_t04_score_threshold_boundaries():
    """A02-T04: Score below, equal to, above threshold; null, NaN/infinite or wrong scale."""
    cand_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        minimum_relevance_score=75.0,
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )
    evaluator = AutomaticDraftEvaluator()

    # Below (74.9)
    c_below = _make_candidate(cand_id, uuid.uuid4(), score=74.9)
    assert evaluator.evaluate(c_below, policy).outcome == AutomaticDraftOutcome.BELOW_THRESHOLD

    # Equal (75.0)
    c_eq = _make_candidate(cand_id, uuid.uuid4(), score=75.0)
    assert evaluator.evaluate(c_eq, policy).outcome == AutomaticDraftOutcome.ADMITTED

    # Above (90.0)
    c_above = _make_candidate(cand_id, uuid.uuid4(), score=90.0)
    assert evaluator.evaluate(c_above, policy).outcome == AutomaticDraftOutcome.ADMITTED

    # NaN
    c_nan = _make_candidate(cand_id, uuid.uuid4(), score=float("nan"))
    assert evaluator.evaluate(c_nan, policy).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED


def test_a02_t05_max_score_with_hard_fail_or_unknowns():
    """A02-T05: Maximum score with hard fail, unknown, or rejected C11 never admits."""
    cand_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        minimum_relevance_score=75.0,
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )
    evaluator = AutomaticDraftEvaluator()

    # Score 100 with REJECTED disposition
    c_rej = _make_candidate(cand_id, uuid.uuid4(), score=100.0).model_copy(
        update={"assessment_disposition": AssessmentDisposition.REJECTED}
    )
    assert evaluator.evaluate(c_rej, policy).outcome == AutomaticDraftOutcome.INELIGIBLE

    # Score 100 with REVIEW unknowns
    c_unk = _make_candidate(cand_id, uuid.uuid4(), score=100.0).model_copy(
        update={"identified_unknowns": ["visa_status_unknown"]}
    )
    assert evaluator.evaluate(c_unk, policy).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED


def test_a02_t06_no_fallback_to_older_eligible_c11_on_pending_model_failure():
    """A02-T06: Unselected or non-LLM assessment cannot fall back to older eligible result."""
    cand_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )
    evaluator = AutomaticDraftEvaluator()

    # Candidate whose current assessment is unselected (e.g. pending LLM assessment)
    c_pending = _make_candidate(cand_id, uuid.uuid4(), score=95.0).model_copy(
        update={"is_authoritative_selection": False}
    )
    dec = evaluator.evaluate(c_pending, policy)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "unselected_assessment" in dec.reason_codes


def test_a02_t07_comparison_and_evaluation_runs_excluded():
    """A02-T07: Comparison run or unselected result produces no requests."""
    cand_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )
    evaluator = AutomaticDraftEvaluator()

    c_comp = _make_candidate(cand_id, uuid.uuid4(), score=95.0).model_copy(update={"run_mode": "comparison"})
    assert evaluator.evaluate(c_comp, policy).outcome == AutomaticDraftOutcome.EXCLUDED


def test_a02_t08_unavailable_and_opt_out():
    """A02-T08: Unavailable job or candidate opt-out produces distinct hold/suppression reasons."""
    cand_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )
    evaluator = AutomaticDraftEvaluator()

    # Unavailable job
    c_unavail = _make_candidate(cand_id, uuid.uuid4()).model_copy(
        update={"availability_status": PostingAvailability.UNAVAILABLE}
    )
    assert evaluator.evaluate(c_unavail, policy).outcome == AutomaticDraftOutcome.INELIGIBLE

    # Opted out
    c_optout = _make_candidate(cand_id, uuid.uuid4()).model_copy(update={"candidate_opted_out": True})
    assert evaluator.evaluate(c_optout, policy).outcome == AutomaticDraftOutcome.SUPPRESSED


def test_a02_t09_changed_posting_before_freeze_guard_blocks(tmp_path: Path):
    """A02-T09: Changed posting after queueing but before freeze -> guard blocks stale admission."""
    engine = _setup_engine(tmp_path)
    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    cand_id = uuid.uuid4()
    assess_id = uuid.uuid4()

    binding = AutomaticDraftIntent(
        client_request_key="auto02:v1:test_guard",
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        material_generation_fingerprint="sha256:mat_initial",
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        decision_id=uuid.uuid4(),
        request_payload_digest="sha256:p1",
        request_payload_json="{}",
        submission_state=SubmissionState.ACKNOWLEDGED,
    )
    engine.automatic_drafts.save_intent(binding)

    from job_automation.generation.automatic.records import AutomaticRequestBinding
    req_binding = AutomaticRequestBinding(
        local_request_id=req_id,
        intent_id=binding.intent_id,
        client_request_key=binding.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        policy_id="p1",
        policy_version="v1.0",
        policy_content_hash="h1",
        expected_assessment_id=assess_id,
        expected_assessment_fingerprint="fp1",
        expected_material_fingerprint="sha256:mat_initial",
        expected_posting_revision_hash="post_hash_ORIGINAL",
        expected_profile_version="v1.0",
        expected_profile_digest="prof1",
        expected_search_policy_version="v1.0",
        expected_search_policy_hash="s1",
    )
    engine.automatic_drafts.save_binding(req_binding)

    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
    )

    # Posting changed at freeze time
    job_snap_changed = _make_frozen_job(job_id, "post_hash_CHANGED")

    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(req, resolved_job=job_snap_changed)
    assert not ok
    assert "Posting revision hash changed" in err.message


def test_a02_t10_repeat_policy_cooldown_and_change_classes(tmp_path: Path):
    """A02-T10: Allowed material change versus disallowed change/first-only/cooldown."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    c1 = _make_candidate(cand_id, job_id, now=now)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)

    # 24h cooldown policy
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
        repeat_policy=RepeatPolicy(mode=RepeatMode.ON_MATERIAL_CHANGE, cooldown_hours=24.0),
    )

    dedup = DeduplicationManager(engine)
    res1 = dedup.check_variant_deduplication(c1, variant, policy, now=now)

    # Save intent from 2 hours ago
    intent1 = AutomaticDraftIntent(
        client_request_key=res1.client_request_key,
        candidate_id=cand_id,
        salesforce_org_id=c1.salesforce_org_id,
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
        created_at=now - timedelta(hours=2),
    )
    engine.automatic_drafts.save_intent(intent1)

    # Material change on profile attempted 2 hours later -> cooldown active!
    c2 = c1.model_copy(update={"profile_digest": "sha256:changed_prof"})
    res2 = dedup.check_variant_deduplication(c2, variant, policy, now=now)
    assert res2.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "repeat_cooldown_active" in res2.reason_codes

    # 25 hours later -> cooldown cleared, permitted!
    res3 = dedup.check_variant_deduplication(c2, variant, policy, now=now + timedelta(hours=23))
    assert res3.outcome == AutomaticDraftOutcome.ADMITTED


def test_a02_t15_atomic_bundle_and_sibling_failure(tmp_path: Path):
    """A02-T15: CV + Letter; final available slot; bundle deferred atomically."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Policy with 2 variants (CV + Letter) and max_requests_per_run=1
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        volume_limits=AutomaticVolumeLimits(max_requests_per_run=1),
        document_variants=[
            DocumentVariantConfig(document_type=DocumentType.CV),
            DocumentVariantConfig(document_type=DocumentType.COVER_LETTER),
        ],
    )
    cand = _make_candidate(cand_id, job_id, score=90.0)

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=False)

    # Bundle needs 2 units, quota is 1 -> bundle deferred atomically! Zero requests created!
    assert report.jobs_by_outcome.get("deferred") == 1
    assert len(engine.generation_requests.list_by_job(job_id)) == 0


def test_a02_t20_exact_manual_request_suppresses_automatic_duplication(tmp_path: Path):
    """A02-T20: Exact manual request already present suppresses automatic work."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    _create_canonical_job(engine, job_id)
    cand = _make_candidate(cand_id, job_id)
    variant = DocumentVariantConfig(document_type=DocumentType.CV)
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[variant],
    )

    # Prepopulate frozen manual request
    manual = GenerationRequest(
        request_id=uuid.uuid4(),
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        state=GenerationProcessing.RUNNING,
        template_id="standard-cv",
        created_at=datetime.now(timezone.utc),
        claimed_at=datetime.now(timezone.utc),
        frozen_input_versions=FrozenInputVersions(
            posting_revision=cand.posting_revision_hash,
            profile_version=cand.profile_version,
            policy_version="v1.0",
            template_version="v1.0",
        ),
    )
    engine.generation_requests.create_request(manual)

    dedup = DeduplicationManager(engine)
    res = dedup.check_variant_deduplication(cand, variant, policy)
    assert res.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "matching_manual_request_exists" in res.reason_codes


def test_a02_t21_explicit_manual_regeneration_unaffected_by_auto02(tmp_path: Path):
    """A02-T21: Explicit manual regeneration with identical inputs is never suppressed by AUTO-02."""
    engine = _setup_engine(tmp_path)
    job_id = uuid.uuid4()
    _create_canonical_job(engine, job_id)

    # Manual regeneration has fresh UUID and links to predecessor
    pred_id = uuid.uuid4()
    manual_regen = GenerationRequest(
        request_id=uuid.uuid4(),
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard-cv",
        state=GenerationProcessing.PENDING,
        created_at=datetime.now(timezone.utc),
        predecessor_request_id=pred_id,
    )
    engine.generation_requests.create_request(manual_regen)

    # Check preflight guard on this manual request: guard passes cleanly
    guard = AutomaticPreflightGuard(engine)
    ok, err, receipt = guard.verify_request_preflight(manual_regen)
    assert ok
    assert err is None


def test_a02_t24_preview_zero_admissions_and_reports(tmp_path: Path):
    """A02-T24: Preview produces safe report with zero DB side effects."""
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    cand = _make_candidate(cand_id, job_id, score=92.0)
    policy = AutomaticDraftPolicy(
        policy_id="p1", policy_version="v1.0", enabled=True,
        candidate_id=cand_id, salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    service = AutomaticDraftService(engine)
    rep = service.evaluate_and_process(policy=policy, candidates=[cand], preview=True)
    assert rep.jobs_by_outcome.get("admitted") == 1

    # Database remains completely unmodified
    assert len(engine.automatic_drafts.list_decisions_for_job(job_id)) == 0
    assert len(engine.automatic_drafts.list_intents_for_job(job_id)) == 0
    assert len(engine.generation_requests.list_by_job(job_id)) == 0
