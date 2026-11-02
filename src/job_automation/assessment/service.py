"""Public evaluation service and RuleEvaluator protocol implementation."""

from __future__ import annotations

import uuid
from typing import Union

from job_automation.assessment.composition import compose_assessment
from job_automation.assessment.deterministic_trace import build_deterministic_trace
from job_automation.assessment.eligibility import evaluate_candidate_eligibility
from job_automation.assessment.hard_rules import evaluate_all_hard_criteria
from job_automation.assessment.inputs import bind_assessment_input
from job_automation.assessment.llm_records import DeterministicDecisionTrace
from job_automation.assessment.models import AssessmentInput
from job_automation.assessment.ports import PostingReader, ProfileReader
from job_automation.assessment.preferences import evaluate_all_preferences
from job_automation.assessment.relevance import assess_relevance
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.interfaces import RuleEvaluator
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import CandidateEligibility, ProfileSnapshot
from job_automation.policy.models import EffectivePolicy


def evaluate_deterministic(assessment_input: AssessmentInput) -> Assessment:
    """Evaluate deterministic eligibility, criteria, and relevance for a bound input.

    Pure function with zero side effects:
    - Never mutates candidate profile, application progress, or availability state.
    - Makes zero external API, model, or network calls.
    - Completely deterministic: identical inputs yield identical outputs.
    """
    posting = assessment_input.posting
    posting_rev = assessment_input.posting_revision
    policy = assessment_input.policy

    # 1. Evaluate hard criteria
    hard_evaluations = evaluate_all_hard_criteria(policy, posting, posting_rev)

    # 2. Evaluate candidate eligibility constraints
    eligibility_checks = evaluate_candidate_eligibility(
        posting,
        posting_rev,
        assessment_input.eligibility,
        assessment_input.profile_version,
        assessment_input.permitted_facts,
    )

    # 3. Evaluate soft preferences
    preferences = evaluate_all_preferences(policy, posting, posting_rev)

    # 4. Assess broad relevance and exclusions
    relevance, exclusions = assess_relevance(policy, posting, posting_rev)

    # 5. Compose and return standard C11 Assessment
    return compose_assessment(
        assessment_input=assessment_input,
        evaluations=hard_evaluations,
        eligibility_checks=eligibility_checks,
        preferences=preferences,
        relevance=relevance,
        exclusions=exclusions,
    )


def evaluate_deterministic_with_trace(
    assessment_input: AssessmentInput,
) -> tuple[Assessment, DeterministicDecisionTrace]:
    """Evaluate deterministic rules and return both C11 Assessment and typed decision trace."""
    posting = assessment_input.posting
    posting_rev = assessment_input.posting_revision
    policy = assessment_input.policy

    # 1. Evaluate hard criteria
    hard_evaluations = evaluate_all_hard_criteria(policy, posting, posting_rev)

    # 2. Evaluate candidate eligibility constraints
    eligibility_checks = evaluate_candidate_eligibility(
        posting,
        posting_rev,
        assessment_input.eligibility,
        assessment_input.profile_version,
        assessment_input.permitted_facts,
    )

    # 3. Evaluate soft preferences
    preferences = evaluate_all_preferences(policy, posting, posting_rev)

    # 4. Assess broad relevance and exclusions
    relevance, exclusions = assess_relevance(policy, posting, posting_rev)

    # 5. Compose C11 assessment
    assessment = compose_assessment(
        assessment_input=assessment_input,
        evaluations=hard_evaluations,
        eligibility_checks=eligibility_checks,
        preferences=preferences,
        relevance=relevance,
        exclusions=exclusions,
    )

    # 6. Build typed trace
    trace = build_deterministic_trace(
        evaluations=hard_evaluations,
        eligibility_checks=eligibility_checks,
        preferences=preferences,
        relevance=relevance,
        exclusions=exclusions,
    )

    return assessment, trace


class AssessmentService:
    """Service facade coordinating deterministic evaluation."""

    def __init__(
        self,
        posting_reader: PostingReader | None = None,
        profile_reader: ProfileReader | None = None,
    ) -> None:
        self.posting_reader = posting_reader
        self.profile_reader = profile_reader

    def evaluate(self, assessment_input: AssessmentInput) -> Assessment:
        """Evaluate an already-bound AssessmentInput."""
        return evaluate_deterministic(assessment_input)

    def evaluate_with_trace(
        self, assessment_input: AssessmentInput
    ) -> tuple[Assessment, DeterministicDecisionTrace]:
        """Evaluate an already-bound AssessmentInput returning both assessment and trace."""
        return evaluate_deterministic_with_trace(assessment_input)

    def evaluate_posting_with_trace(
        self,
        canonical_job_id: uuid.UUID,
        posting_revision: str,
        posting: NormalizedPosting,
        policy: Union[EffectivePolicy, SearchPolicy],
        profile: ProfileSnapshot | None = None,
        profile_version: str | None = None,
        eligibility: CandidateEligibility | None = None,
        execution_id: uuid.UUID | None = None,
    ) -> tuple[Assessment, DeterministicDecisionTrace]:
        """Bind inputs and evaluate deterministic rules returning both assessment and trace."""
        bound_input = bind_assessment_input(
            canonical_job_id=canonical_job_id,
            posting_revision=posting_revision,
            posting=posting,
            policy=policy,
            profile=profile,
            profile_version=profile_version,
            eligibility=eligibility,
            execution_id=execution_id,
        )
        return self.evaluate_with_trace(bound_input)

    def evaluate_posting(
        self,
        canonical_job_id: uuid.UUID,
        posting_revision: str,
        posting: NormalizedPosting,
        policy: Union[EffectivePolicy, SearchPolicy],
        profile: ProfileSnapshot | None = None,
        profile_version: str | None = None,
        eligibility: CandidateEligibility | None = None,
        execution_id: uuid.UUID | None = None,
    ) -> Assessment:
        """Bind inputs and evaluate deterministic rules."""
        bound_input = bind_assessment_input(
            canonical_job_id=canonical_job_id,
            posting_revision=posting_revision,
            posting=posting,
            policy=policy,
            profile=profile,
            profile_version=profile_version,
            eligibility=eligibility,
            execution_id=execution_id,
        )
        return self.evaluate(bound_input)


class DeterministicRuleEvaluator:
    """Implements RuleEvaluator protocol (Boundary 4)."""

    def __init__(
        self,
        posting_reader: PostingReader | None = None,
        profile_reader: ProfileReader | None = None,
    ) -> None:
        self.posting_reader = posting_reader
        self.profile_reader = profile_reader
        self.service = AssessmentService(
            posting_reader=posting_reader,
            profile_reader=profile_reader,
        )

    def evaluate_rules(
        self,
        revision: PostingRevision,
        policy: SearchPolicy,
        eligibility: CandidateEligibility,
    ) -> Assessment:
        """Protocol conformance implementation of evaluate_rules."""
        posting: NormalizedPosting | None = None

        if self.posting_reader is not None:
            posting = self.posting_reader.get_normalized_posting(revision.source_key)

        if posting is None:
            # Fallback to minimal posting constructed from revision if reader unavailable
            first_url = revision.source_urls[0] if revision.source_urls else "https://example.com/job"
            posting = NormalizedPosting(
                source_key=revision.source_key,
                normalizer_version="1.0-revision-fallback",
                raw_reference="synthetic-revision-ref",
                raw_content_hash=revision.content_hash,
                company_name_hint="Company",
                title=revision.title,
                description_clean=revision.title,
                source_url=first_url,
                observed_at=revision.first_seen_at,
            )

        bound_input = bind_assessment_input(
            canonical_job_id=revision.canonical_job_id,
            posting_revision=revision.content_hash,
            posting=posting,
            policy=policy,
            profile_version="v1.0-evaluator",
            eligibility=eligibility,
        )
        return self.service.evaluate(bound_input)

