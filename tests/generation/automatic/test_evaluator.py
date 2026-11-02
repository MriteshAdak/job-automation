"""Tests for AutomaticDraftEvaluator ordered eligibility rules."""

import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    DocumentType,
    PostingAvailability,
)
from job_automation.generation.automatic.evaluator import AutomaticDraftEvaluator
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
)


def _base_policy(candidate_id: uuid.UUID, org_id: str = "00D000000000001EAA") -> AutomaticDraftPolicy:
    return AutomaticDraftPolicy(
        policy_id="test-policy",
        policy_version="v1.0",
        enabled=True,
        candidate_id=candidate_id,
        salesforce_org_id=org_id,
        minimum_relevance_score=75.0,
        score_scale="0-100",
        allowed_application_states=["New", "Shortlisted"],
        max_assessment_age_hours=72.0,
        max_availability_age_hours=48.0,
        max_candidate_control_age_hours=24.0,
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )


def _base_candidate(candidate_id: uuid.UUID, org_id: str = "00D000000000001EAA", now: datetime | None = None) -> AutomaticDraftCandidate:
    ref_time = now or datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    return AutomaticDraftCandidate(
        candidate_id=candidate_id,
        salesforce_org_id=org_id,
        canonical_job_id=uuid.uuid4(),
        assessment_id=uuid.uuid4(),
        assessment_input_fingerprint="sha256:fp",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=80.0,
        score_scale="0-100",
        evaluated_at=ref_time - timedelta(hours=1),
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:rev",
        normalized_content_hash="sha256:norm",
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


def test_gate1_policy_disabled():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id).model_copy(update={"enabled": False})
    cand = _base_candidate(cand_id, now=now)

    evaluator = AutomaticDraftEvaluator()
    dec = evaluator.evaluate(cand, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.DISABLED
    assert "policy_disabled" in dec.reason_codes


def test_gate2_excluded_run_and_scope_mismatch():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    # Evaluation mode
    cand_eval = _base_candidate(cand_id, now=now).model_copy(update={"run_mode": "evaluation"})
    dec = evaluator.evaluate(cand_eval, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.EXCLUDED
    assert "non_production_run" in dec.reason_codes

    # Candidate mismatch
    cand_other = _base_candidate(uuid.uuid4(), now=now)
    dec = evaluator.evaluate(cand_other, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.EXCLUDED
    assert "candidate_mismatch" in dec.reason_codes

    # Org mismatch
    cand_org = _base_candidate(cand_id, org_id="00D999999999999EAA", now=now)
    dec = evaluator.evaluate(cand_org, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.EXCLUDED
    assert "org_mismatch" in dec.reason_codes


def test_gate3_unselected_or_stale_or_non_llm():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    # Not authoritative selection
    cand_unsel = _base_candidate(cand_id, now=now).model_copy(update={"is_authoritative_selection": False})
    dec = evaluator.evaluate(cand_unsel, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "unselected_assessment" in dec.reason_codes

    # Rules only assessment
    cand_rules = _base_candidate(cand_id, now=now).model_copy(update={"assessment_method": "rules"})
    dec = evaluator.evaluate(cand_rules, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "non_llm_assessment" in dec.reason_codes

    # Stale assessment (> 72 hours)
    cand_stale = _base_candidate(cand_id, now=now).model_copy(update={"evaluated_at": now - timedelta(hours=73)})
    dec = evaluator.evaluate(cand_stale, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "assessment_stale" in dec.reason_codes

    # Future clock skew (> 60s in future)
    cand_future = _base_candidate(cand_id, now=now).model_copy(update={"evaluated_at": now + timedelta(seconds=120)})
    dec = evaluator.evaluate(cand_future, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "assessment_future_clock_skew" in dec.reason_codes


def test_gate4_assessment_rejection():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    cand_rej = _base_candidate(cand_id, now=now).model_copy(
        update={"assessment_disposition": AssessmentDisposition.REJECTED, "relevance_score": 95.0}
    )
    dec = evaluator.evaluate(cand_rej, policy, now=now)
    # Score 95 cannot rescue rejection!
    assert dec.outcome == AutomaticDraftOutcome.INELIGIBLE
    assert "assessment_rejected" in dec.reason_codes


def test_gate5_review_and_unknowns():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    # Disposition REVIEW
    cand_rev = _base_candidate(cand_id, now=now).model_copy(update={"assessment_disposition": AssessmentDisposition.REVIEW})
    dec = evaluator.evaluate(cand_rev, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "assessment_disposition_review" in dec.reason_codes

    # Identified unknowns
    cand_unk = _base_candidate(cand_id, now=now).model_copy(update={"identified_unknowns": ["german_c1_level"]})
    dec = evaluator.evaluate(cand_unk, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "identified_unknowns_present" in dec.reason_codes

    # Validation issues
    cand_iss = _base_candidate(cand_id, now=now).model_copy(update={"validation_issues": ["unsupported_claim"]})
    dec = evaluator.evaluate(cand_iss, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "validation_issues_present" in dec.reason_codes


def test_gate6_rule_coverage():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    cand_cov = _base_candidate(cand_id, now=now).model_copy(update={"rule_coverage_complete": False})
    dec = evaluator.evaluate(cand_cov, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED
    assert "rule_coverage_incomplete" in dec.reason_codes


def test_gate7_score_threshold_and_invalid():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)  # threshold = 75.0
    evaluator = AutomaticDraftEvaluator()

    # Missing score
    cand_noscore = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": None})
    assert evaluator.evaluate(cand_noscore, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # NaN score
    cand_nan = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": float("nan")})
    assert evaluator.evaluate(cand_nan, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # Out of range (> 100)
    cand_high = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": 105.0})
    assert evaluator.evaluate(cand_high, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # Below threshold (74.9 < 75.0)
    cand_below = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": 74.9})
    dec_below = evaluator.evaluate(cand_below, policy, now=now)
    assert dec_below.outcome == AutomaticDraftOutcome.BELOW_THRESHOLD
    assert "score_below_threshold" in dec_below.reason_codes

    # Exactly at threshold (75.0 == 75.0) -> Passes!
    cand_exact = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": 75.0})
    assert evaluator.evaluate(cand_exact, policy, now=now).outcome == AutomaticDraftOutcome.ADMITTED

    # Above threshold (85.0 > 75.0) -> Passes!
    cand_above = _base_candidate(cand_id, now=now).model_copy(update={"relevance_score": 85.0})
    assert evaluator.evaluate(cand_above, policy, now=now).outcome == AutomaticDraftOutcome.ADMITTED


def test_gate8_availability():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    # Unavailable job
    cand_unavail = _base_candidate(cand_id, now=now).model_copy(update={"availability_status": PostingAvailability.UNAVAILABLE})
    dec = evaluator.evaluate(cand_unavail, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.INELIGIBLE
    assert "job_unavailable" in dec.reason_codes

    # Uncertain / not seen
    cand_notseen = _base_candidate(cand_id, now=now).model_copy(update={"availability_status": PostingAvailability.NOT_SEEN})
    assert evaluator.evaluate(cand_notseen, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # Stale availability (> 48 hours)
    cand_avail_stale = _base_candidate(cand_id, now=now).model_copy(
        update={"availability_observed_at": now - timedelta(hours=50)}
    )
    assert evaluator.evaluate(cand_avail_stale, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED


def test_gate9_profile_missing():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    cand_noprof = _base_candidate(cand_id, now=now).model_copy(update={"profile_version": "", "profile_digest": ""})
    dec = evaluator.evaluate(cand_noprof, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.BLOCKED
    assert "profile_missing" in dec.reason_codes


def test_gate10_candidate_control_and_opt_out():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    # Opted out
    cand_optout = _base_candidate(cand_id, now=now).model_copy(update={"candidate_opted_out": True})
    dec = evaluator.evaluate(cand_optout, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "candidate_opted_out" in dec.reason_codes

    # Missing state
    cand_nostate = _base_candidate(cand_id, now=now).model_copy(update={"candidate_application_state": None})
    assert evaluator.evaluate(cand_nostate, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # Stale observation (> 24 hours)
    cand_stale_ctrl = _base_candidate(cand_id, now=now).model_copy(
        update={"candidate_control_observed_at": now - timedelta(hours=26)}
    )
    assert evaluator.evaluate(cand_stale_ctrl, policy, now=now).outcome == AutomaticDraftOutcome.REVIEW_REQUIRED

    # Disallowed state (e.g. Applied)
    cand_applied = _base_candidate(cand_id, now=now).model_copy(update={"candidate_application_state": "Applied"})
    dec = evaluator.evaluate(cand_applied, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.SUPPRESSED
    assert "application_state_disallowed" in dec.reason_codes


def test_gate11_all_pass_admitted():
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    cand_id = uuid.uuid4()
    policy = _base_policy(cand_id)
    evaluator = AutomaticDraftEvaluator()

    cand = _base_candidate(cand_id, now=now)
    dec = evaluator.evaluate(cand, policy, now=now)
    assert dec.outcome == AutomaticDraftOutcome.ADMITTED
    assert "eligibility_verified" in dec.reason_codes
    assert dec.proposed_document_types == [DocumentType.CV]

