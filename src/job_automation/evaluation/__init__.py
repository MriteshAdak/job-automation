"""Evaluation and benchmark subsystem for JSON vs RAG context comparisons (EVAL-01).

Implements:
- Paired reproducible JSON and RAG evaluation on synthetic labeled corpus.
- Rigorous evidence attribution (retrieval coverage, admitted coverage, citation usage).
- Honest matching error quantification and confusion matrices.
- Rejected-job sampling and audit.
- Human review feedback and corrections without mutating candidate truth.
- Strict publication isolation (zero Salesforce effects).
"""

from __future__ import annotations

from job_automation.evaluation.errors import (
    DatabaseAliasingError,
    EvaluationError,
    InputTamperingError,
    InvalidCorpusError,
    MismatchedArmControlError,
    PublicationAttemptBlockedError,
    UnavailablePhase1ExtensionError,
)
from job_automation.evaluation.records import (
    ArmAttempt,
    DependencyGate,
    DependencyGateRegister,
    EvaluationCase,
    ExperimentManifest,
    GoldLabelRevision,
    GoldRequirementLabel,
    MetricReport,
    PairResult,
    ReviewCorrection,
    SampleManifest,
)
from job_automation.evaluation.settings import (
    DEFAULT_EVAL_DB_NAME,
    EVAL_SCHEMA_VERSION,
    EvaluationSettings,
    METRIC_SPEC_VERSION,
    PHASE1_EXTENSIONS_STATUS,
    PROPOSED_TARGETS,
)

__all__ = [
    "ArmAttempt",
    "DatabaseAliasingError",
    "DependencyGate",
    "DependencyGateRegister",
    "EvaluationCase",
    "EvaluationError",
    "EvaluationSettings",
    "ExperimentManifest",
    "GoldLabelRevision",
    "GoldRequirementLabel",
    "InputTamperingError",
    "InvalidCorpusError",
    "MetricReport",
    "MismatchedArmControlError",
    "PairResult",
    "PublicationAttemptBlockedError",
    "ReviewCorrection",
    "SampleManifest",
    "UnavailablePhase1ExtensionError",
    "DEFAULT_EVAL_DB_NAME",
    "EVAL_SCHEMA_VERSION",
    "METRIC_SPEC_VERSION",
    "PHASE1_EXTENSIONS_STATUS",
    "PROPOSED_TARGETS",
]

