"""MATCH-01 — Deterministic eligibility and keyword matching component."""

from __future__ import annotations

from job_automation.assessment.deterministic_trace import build_deterministic_trace
from job_automation.assessment.errors import (
    AssessmentConfigurationError,
    AssessmentError,
    AssessmentInputError,
    FieldEvaluationError,
)
from job_automation.assessment.inputs import bind_assessment_input
from job_automation.assessment.llm_errors import LLMAssessmentError, make_pending_result
from job_automation.assessment.llm_inputs import compute_assessment_input_fingerprint
from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentMode,
    AssessmentProposal,
    AssessmentRequest,
    AssessmentRunResult,
    DeterministicDecisionTrace,
    FindingStatus,
    RequirementCategory,
    RequirementItem,
    RequirementIssue,
    RequirementObligation,
    RequirementFindingProposal,
    RequirementSet,
)
from job_automation.assessment.llm_service import (
    LegacyAssessorAdapter,
    LLMAssessmentService,
)
from job_automation.assessment.llm_settings import (
    DEFAULT_LLM_ASSESSMENT_SETTINGS,
    LLMAssessmentSettings,
)
from job_automation.assessment.models import (
    EVALUATOR_VERSION,
    AssessmentInput,
    CriterionEvaluation,
    ExclusionOutcome,
    FactualOutcome,
    MissingActionSource,
    PreferenceOutcome,
    RelevanceAssessmentResult,
)
from job_automation.assessment.requirements import (
    prepare_deterministic_requirements,
    prepare_llm_requirements,
    prepare_requirements,
    to_requirement_query_set,
)
from job_automation.assessment.service import (
    AssessmentService,
    DeterministicRuleEvaluator,
    evaluate_deterministic,
    evaluate_deterministic_with_trace,
)

__all__ = [
    "DEFAULT_LLM_ASSESSMENT_SETTINGS",
    "EVALUATOR_VERSION",
    "AssessmentConfigurationError",
    "AssessmentError",
    "AssessmentInput",
    "AssessmentInputError",
    "AssessmentLimits",
    "AssessmentMode",
    "AssessmentProposal",
    "AssessmentRequest",
    "AssessmentRunResult",
    "AssessmentService",
    "CriterionEvaluation",
    "DeterministicDecisionTrace",
    "DeterministicRuleEvaluator",
    "ExclusionOutcome",
    "FactualOutcome",
    "FieldEvaluationError",
    "FindingStatus",
    "LLMAssessmentError",
    "LLMAssessmentService",
    "LLMAssessmentSettings",
    "LegacyAssessorAdapter",
    "MissingActionSource",
    "PreferenceOutcome",
    "RelevanceAssessmentResult",
    "RequirementCategory",
    "RequirementFindingProposal",
    "RequirementIssue",
    "RequirementItem",
    "RequirementObligation",
    "RequirementSet",
    "bind_assessment_input",
    "build_deterministic_trace",
    "compute_assessment_input_fingerprint",
    "evaluate_deterministic",
    "evaluate_deterministic_with_trace",
    "make_pending_result",
    "prepare_deterministic_requirements",
    "prepare_llm_requirements",
    "prepare_requirements",
    "to_requirement_query_set",
]

