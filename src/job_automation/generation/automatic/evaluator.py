"""Authoritative eligibility evaluator for AUTO-02 automatic drafting.

Implements the strict, ordered eligibility table from AUTO-02:
1. Policy disabled / invalid
2. Evaluation / comparison / non-production run or candidate/org mismatch
3. Unselected, non-LLM, stale, or future clock-skewed assessment
4. Hard fail, missing-info rejection, explicit exclusion, C11 REJECTED
5. Hard unknown, C11 REVIEW, identified unknowns, or validation issues
6. Deterministic rule coverage incomplete
7. Relevance score missing, NaN/infinite, out-of-range, or below threshold
8. Posting unavailable, uncertain, or stale
9. Unapproved profile or missing purpose permissions
10. Candidate opted out, state unknown, state stale, or disallowed application state
11. Qualified / admitted for drafting proposals
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone

from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
)
from job_automation.generation.automatic.fingerprints import (
    compute_decision_input_fingerprint,
)
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftDecision,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
)


class AutomaticDraftEvaluator:
    """Pure deterministic evaluator producing explainable admission decisions."""

    def __init__(self, engine_version: str = "1.0") -> None:
        self.engine_version = engine_version

    def evaluate(
        self,
        candidate: AutomaticDraftCandidate,
        policy: AutomaticDraftPolicy,
        now: datetime | None = None,
        evaluation_run_id: uuid.UUID | None = None,
        evaluation_attempt_id: uuid.UUID | None = None,
    ) -> AutomaticDraftDecision:
        """Evaluate a candidate envelope against the versioned policy."""
        now_utc = now or datetime.now(timezone.utc)
        run_id = evaluation_run_id or candidate.run_id or uuid.uuid4()
        attempt_id = evaluation_attempt_id or uuid.uuid4()

        decision_fingerprint = compute_decision_input_fingerprint(
            candidate=candidate,
            policy=policy,
            engine_version=self.engine_version,
        )

        outcome, reason_codes, summary_reason = self._evaluate_gates(
            candidate=candidate,
            policy=policy,
            now=now_utc,
        )

        proposed_types = (
            [v.document_type for v in policy.document_variants]
            if outcome == AutomaticDraftOutcome.ADMITTED
            else []
        )

        return AutomaticDraftDecision(
            candidate_id=candidate.candidate_id,
            salesforce_org_id=candidate.salesforce_org_id,
            canonical_job_id=candidate.canonical_job_id,
            evaluation_run_id=run_id,
            evaluation_attempt_id=attempt_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_content_hash=policy.policy_content_hash or "unhashed",
            decision_input_fingerprint=decision_fingerprint,
            outcome=outcome,
            reason_codes=reason_codes,
            summary_reason=summary_reason,
            evaluated_at=now_utc,
            relevance_score=candidate.relevance_score,
            threshold_applied=policy.minimum_relevance_score,
            assessment_ref=candidate.assessment_id,
            proposed_document_types=proposed_types,
        )

    def _evaluate_gates(
        self,
        candidate: AutomaticDraftCandidate,
        policy: AutomaticDraftPolicy,
        now: datetime,
    ) -> tuple[AutomaticDraftOutcome, list[str], str]:
        skew_tolerance = timedelta(seconds=policy.clock_skew_tolerance_seconds)

        # Gate 1: Policy disabled
        if not policy.enabled:
            return (
                AutomaticDraftOutcome.DISABLED,
                ["policy_disabled"],
                "Automatic drafting policy is disabled.",
            )

        # Gate 2: Excluded run mode, candidate mismatch, or org mismatch
        if candidate.run_mode in ("evaluation", "comparison"):
            return (
                AutomaticDraftOutcome.EXCLUDED,
                ["non_production_run"],
                f"Candidate evaluation run mode '{candidate.run_mode}' is not production.",
            )
        if candidate.candidate_id != policy.candidate_id:
            return (
                AutomaticDraftOutcome.EXCLUDED,
                ["candidate_mismatch"],
                f"Candidate UUID '{candidate.candidate_id}' does not match policy scope '{policy.candidate_id}'.",
            )
        if candidate.salesforce_org_id != policy.salesforce_org_id:
            return (
                AutomaticDraftOutcome.EXCLUDED,
                ["org_mismatch"],
                f"Salesforce Org ID '{candidate.salesforce_org_id}' does not match policy scope '{policy.salesforce_org_id}'.",
            )

        # Gate 3: Authoritative selection & assessment method & freshness
        if not candidate.is_authoritative_selection:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["unselected_assessment"],
                "Assessment is not marked as the authoritative final selection.",
            )
        if candidate.assessment_method != "llm":
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["non_llm_assessment"],
                f"Assessment method '{candidate.assessment_method}' is not authoritative LLM assessment.",
            )

        # Timestamp in future beyond clock skew tolerance
        if candidate.evaluated_at > now + skew_tolerance:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["assessment_future_clock_skew"],
                "Assessment evaluated_at timestamp is in the future beyond clock skew tolerance.",
            )

        # Assessment staleness
        max_assessment_age = timedelta(hours=policy.max_assessment_age_hours)
        if now - candidate.evaluated_at > max_assessment_age + skew_tolerance:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["assessment_stale"],
                f"Assessment age ({now - candidate.evaluated_at}) exceeds limit ({max_assessment_age}).",
            )

        # Gate 4: Assessment rejection (hard fail, missing info, exclusions)
        if candidate.assessment_disposition == AssessmentDisposition.REJECTED:
            return (
                AutomaticDraftOutcome.INELIGIBLE,
                ["assessment_rejected"],
                "Candidate was rejected by assessment (hard failure or missing-info rejection).",
            )

        # Gate 5: Assessment review, unknowns, validation issues
        if candidate.assessment_disposition == AssessmentDisposition.REVIEW:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["assessment_disposition_review"],
                "Assessment final disposition is REVIEW; human review required.",
            )
        if candidate.identified_unknowns:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["identified_unknowns_present"],
                f"Assessment has unresolved unknowns: {', '.join(candidate.identified_unknowns)}.",
            )
        if candidate.validation_issues:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["validation_issues_present"],
                f"Assessment has validation issues: {', '.join(candidate.validation_issues)}.",
            )

        # Gate 6: Rule coverage completeness
        if not candidate.rule_coverage_complete:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["rule_coverage_incomplete"],
                "Authoritative deterministic rule coverage is missing or incomplete.",
            )

        # Gate 7: Relevance score validation & threshold
        if candidate.relevance_score is None:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["missing_relevance_score"],
                "Assessment lacks numeric relevance score.",
            )
        if math.isnan(candidate.relevance_score) or math.isinf(candidate.relevance_score):
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["invalid_relevance_score"],
                "Assessment relevance score is NaN or Infinite.",
            )
        if candidate.relevance_score < 0.0 or candidate.relevance_score > 100.0:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["score_out_of_range"],
                f"Assessment relevance score {candidate.relevance_score} is out of 0-100 range.",
            )
        if candidate.relevance_score < policy.minimum_relevance_score:
            return (
                AutomaticDraftOutcome.BELOW_THRESHOLD,
                ["score_below_threshold"],
                f"Relevance score ({candidate.relevance_score:.1f}) is below policy threshold ({policy.minimum_relevance_score:.1f}).",
            )

        # Gate 8: Availability
        if candidate.availability_status == PostingAvailability.UNAVAILABLE:
            return (
                AutomaticDraftOutcome.INELIGIBLE,
                ["job_unavailable"],
                "Job posting is unavailable; automatic drafting never overrides unavailability.",
            )
        if candidate.availability_status in (PostingAvailability.UNKNOWN, PostingAvailability.NOT_SEEN):
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["availability_uncertain"],
                f"Job posting availability is uncertain ({candidate.availability_status.value}).",
            )
        if candidate.availability_observed_at is None:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["availability_observation_missing"],
                "Availability observation timestamp is missing.",
            )
        max_availability_age = timedelta(hours=policy.max_availability_age_hours)
        if now - candidate.availability_observed_at > max_availability_age + skew_tolerance:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["availability_stale"],
                f"Availability observation age exceeds limit ({max_availability_age}).",
            )

        # Gate 9: Candidate profile approval & purpose permissions
        if not candidate.profile_version or not candidate.profile_digest:
            return (
                AutomaticDraftOutcome.BLOCKED,
                ["profile_missing"],
                "Approved candidate profile is missing.",
            )
        if candidate.profile_snapshot is not None and not candidate.profile_snapshot.approved_by_candidate:
            return (
                AutomaticDraftOutcome.BLOCKED,
                ["profile_unapproved"],
                "Candidate profile has not received candidate approval.",
            )

        # Gate 10: Candidate control, opt-out, and application state
        if candidate.candidate_opted_out:
            return (
                AutomaticDraftOutcome.SUPPRESSED,
                ["candidate_opted_out"],
                "Candidate has explicitly opted out of automatic drafting.",
            )
        if candidate.candidate_application_state is None:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["candidate_state_unknown"],
                "Candidate application state observation is missing.",
            )
        if candidate.candidate_control_observed_at is None:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["candidate_control_observation_missing"],
                "Candidate control observation timestamp is missing.",
            )
        max_control_age = timedelta(hours=policy.max_candidate_control_age_hours)
        if now - candidate.candidate_control_observed_at > max_control_age + skew_tolerance:
            return (
                AutomaticDraftOutcome.REVIEW_REQUIRED,
                ["candidate_control_stale"],
                f"Candidate control observation age exceeds limit ({max_control_age}).",
            )
        if candidate.candidate_application_state not in policy.allowed_application_states:
            return (
                AutomaticDraftOutcome.SUPPRESSED,
                ["application_state_disallowed"],
                f"Application state '{candidate.candidate_application_state}' is not in policy allowlist {policy.allowed_application_states}.",
            )

        # Gate 11: All gates passed -> Admitted
        return (
            AutomaticDraftOutcome.ADMITTED,
            ["eligibility_verified"],
            "Candidate meets all eligibility, threshold, availability, and candidate-control criteria.",
        )

