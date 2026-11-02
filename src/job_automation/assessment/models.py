"""Domain models for MATCH-01 deterministic assessment."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Union

from pydantic import Field

from job_automation.contracts.assessment import RuleOutcome
from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import (
    AssessmentDisposition,
    HardCriterionResult,
)
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileSnapshot,
)
from job_automation.policy.models import EffectivePolicy

EVALUATOR_VERSION: str = "1.0"


class FactualOutcome(str, Enum):
    """Factual evaluation outcome for a criterion before policy missing-action is applied."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class MissingActionSource(str, Enum):
    """Source of the missing information action."""

    EXPLICIT_RULE = "explicit_rule"
    FIELD_DEFAULT = "field_default"
    GLOBAL_DEFAULT = "global_default"
    NOT_APPLICABLE = "not_applicable"


class CriterionEvaluation(ContractModel):
    """Detailed intermediate evaluation result for a single hard criterion."""

    criterion_id: str = Field(min_length=1, description="Criterion ID from policy")
    criterion_name: str = Field(min_length=1, description="Human-readable criterion label")
    target_field: str = Field(min_length=1, description="Evaluated posting field path")
    factual_result: FactualOutcome = Field(
        description="Factual comparison result before policy missing-action"
    )
    effective_action: str = Field(
        description="Effective missing action ('pass', 'fail', 'unknown') or 'not_applicable'"
    )
    missing_action_source: MissingActionSource = Field(
        default=MissingActionSource.NOT_APPLICABLE,
        description="Where the missing action originated from",
    )
    is_waived: bool = Field(
        default=False,
        description="True if factual unknown was waived by an on_missing='pass' policy action",
    )
    is_policy_rejection: bool = Field(
        default=False,
        description="True if factual unknown caused rejection due to an on_missing='fail' policy action",
    )
    job_evidence: JobEvidenceReference | None = Field(
        default=None,
        description="Job posting evidence supporting the outcome",
    )
    candidate_evidence: CandidateEvidenceReference | None = Field(
        default=None,
        description="Candidate profile evidence supporting the outcome",
    )
    reason: str = Field(min_length=1, description="Detailed explanation of the outcome")
    missing_field: str | None = Field(
        default=None,
        description="Field name that was missing if factual_result is UNKNOWN",
    )

    def to_rule_outcome(self) -> RuleOutcome:
        """Convert to standard C11 RuleOutcome."""
        if self.is_policy_rejection:
            res = HardCriterionResult.FAIL
        elif self.is_waived:
            res = HardCriterionResult.PASS
        elif self.factual_result == FactualOutcome.PASS:
            res = HardCriterionResult.PASS
        elif self.factual_result == FactualOutcome.FAIL:
            res = HardCriterionResult.FAIL
        else:
            res = HardCriterionResult.UNKNOWN

        ev = self.job_evidence or self.candidate_evidence
        return RuleOutcome(
            criterion_id=self.criterion_id,
            criterion_name=self.criterion_name,
            result=res,
            evidence=ev,
            reason=self.reason,
        )


class PreferenceOutcome(ContractModel):
    """Evaluation result for a soft preference rule."""

    rule_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    field: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0)
    matched: bool = Field(description="True if preference was satisfied")
    is_unknown: bool = Field(
        default=False,
        description="True if target field was missing or ambiguous",
    )
    reason: str = Field(min_length=1)
    job_evidence: JobEvidenceReference | None = Field(default=None)


class ExclusionOutcome(ContractModel):
    """Result of evaluating explicit exclusions and negative keywords."""

    excluded: bool = Field(description="True if an explicit exclusion was triggered")
    reason: str | None = Field(
        default=None,
        description="Explanation if exclusion was triggered or proposed",
    )
    matched_term: str | None = Field(default=None)
    field: str | None = Field(default=None)
    is_review_proposal: bool = Field(
        default=False,
        description="True if match was ambiguous or incidental in description, proposing review",
    )
    job_evidence: JobEvidenceReference | None = Field(default=None)


class RelevanceAssessmentResult(ContractModel):
    """Relevance assessment outcome combining broad keywords, exclusions, and preferences."""

    decision: AssessmentDisposition = Field(
        description="Relevance disposition: ELIGIBLE, REVIEW, or REJECTED"
    )
    broad_keyword_hits: list[str] = Field(
        default_factory=list,
        description="Broad keywords matched in title or description",
    )
    broad_keyword_misses: list[str] = Field(
        default_factory=list,
        description="Broad keywords not found",
    )
    negative_keyword_hits: list[str] = Field(
        default_factory=list,
        description="Negative keywords matched",
    )
    reason: str = Field(min_length=1, description="Relevance rationale")
    job_evidence: list[JobEvidenceReference] = Field(
        default_factory=list,
        description="Job evidence references supporting relevance",
    )


class AssessmentInput(ContractModel):
    """Immutable, validated input required to evaluate deterministic rules for a posting."""

    canonical_job_id: uuid.UUID = Field(description="Canonical job UUID")
    posting_revision: str = Field(
        min_length=1,
        description="Posting revision identifier or content hash",
    )
    posting: NormalizedPosting = Field(description="Exact C06 normalized posting evaluated")
    policy: Union[EffectivePolicy, SearchPolicy] = Field(
        description="Effective or search policy governing evaluation"
    )
    profile: ProfileSnapshot | None = Field(
        default=None,
        description="Optional full approved candidate profile snapshot",
    )
    profile_version: str = Field(
        min_length=1,
        description="Version string of the candidate profile evaluated",
    )
    eligibility: CandidateEligibility = Field(
        description="Approved candidate eligibility facts"
    )
    permitted_facts: list[CandidateFact] = Field(
        default_factory=list,
        description="Candidate evidence facts permitted for purpose='assessment'",
    )
    execution_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique execution UUID for this assessment run",
    )
    evaluator_version: str = Field(
        default=EVALUATOR_VERSION,
        description="Evaluator implementation version",
    )

