"""Input binding and validation for MATCH-01 deterministic assessment."""

from __future__ import annotations

import uuid
from typing import Union

from job_automation.assessment.errors import AssessmentInputError
from job_automation.assessment.models import AssessmentInput
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileSnapshot,
)
from job_automation.policy.models import EffectivePolicy
from job_automation.profile.inclusion import InclusionRules


def bind_assessment_input(
    canonical_job_id: uuid.UUID,
    posting_revision: str,
    posting: NormalizedPosting,
    policy: Union[EffectivePolicy, SearchPolicy],
    profile: ProfileSnapshot | None = None,
    profile_version: str | None = None,
    eligibility: CandidateEligibility | None = None,
    permitted_facts: list[CandidateFact] | None = None,
    execution_id: uuid.UUID | None = None,
) -> AssessmentInput:
    """Validate and bind evaluation inputs into an immutable AssessmentInput.

    Enforces:
    - Profile must be explicitly human-approved; unapproved snapshots are rejected.
    - Applies purpose='assessment' inclusion rules so private/unrelated candidate facts
      are never exposed to the assessment evaluator.
    - Policy must be validated and carry an effective version fingerprint.
    - Exact C06 posting content is bound to the target canonical ID and revision.
    """
    if not isinstance(posting, NormalizedPosting):
        raise AssessmentInputError(
            f"Expected NormalizedPosting, got {type(posting).__name__}"
        )

    # Validate profile snapshot if provided
    final_profile_version: str
    final_eligibility: CandidateEligibility
    final_permitted_facts: list[CandidateFact]

    if profile is not None:
        if not profile.approval_metadata.is_approved:
            raise AssessmentInputError(
                f"Candidate profile version '{profile.profile_version}' is not approved for use"
            )

        final_profile_version = profile.profile_version
        final_eligibility = profile.explicit_eligibility

        # Filter permitted facts for assessment purpose using PROFILE-01 InclusionRules
        view = InclusionRules().evaluate_inclusion(profile, purpose="assessment")
        final_permitted_facts = view.eligible_facts
    else:
        if not profile_version or not profile_version.strip():
            raise AssessmentInputError("profile_version must be provided when profile snapshot is omitted")
        if eligibility is None:
            raise AssessmentInputError("eligibility must be provided when profile snapshot is omitted")

        final_profile_version = profile_version.strip()
        final_eligibility = eligibility
        final_permitted_facts = permitted_facts or []

    # Validate policy version
    policy_ver: str
    if isinstance(policy, EffectivePolicy):
        policy_ver = policy.policy.policy_version
    elif isinstance(policy, SearchPolicy):
        policy_ver = policy.policy_version
    else:
        raise AssessmentInputError(f"Expected EffectivePolicy or SearchPolicy, got {type(policy).__name__}")

    if not policy_ver or not policy_ver.strip():
        raise AssessmentInputError("Policy must carry a valid policy_version fingerprint")

    if not posting_revision or not posting_revision.strip():
        raise AssessmentInputError("posting_revision reference cannot be empty")

    return AssessmentInput(
        canonical_job_id=canonical_job_id,
        posting_revision=posting_revision.strip(),
        posting=posting,
        policy=policy,
        profile=profile,
        profile_version=final_profile_version,
        eligibility=final_eligibility,
        permitted_facts=final_permitted_facts,
        execution_id=execution_id or uuid.uuid4(),
    )
