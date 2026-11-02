"""Interfaces, protocols, and architectural boundary guards for evaluation (EVAL-01-S01).

Enforces:
- Negative boundary: model inputs NEVER include gold labels or reviewer comments.
- Negative boundary: evaluation runner NEVER has Salesforce publication credentials or outbox authority.
- Protocols for corpus loading, evaluation persistence, and runner execution.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence
from job_automation.contracts.enums import ContextStrategy
from job_automation.evaluation.errors import PublicationAttemptBlockedError


class EvaluationRunnerPort(Protocol):
    """Protocol for running paired evaluations."""

    def run_experiment(self, manifest: Any, corpus: Any) -> Any:
        ...


class EvaluationRepositoryPort(Protocol):
    """Protocol for isolated evaluation persistence."""

    def save_experiment(self, manifest: Any) -> None:
        ...

    def save_pair_result(self, pair: Any) -> None:
        ...

    def get_incomplete_pairs(self, experiment_id: Any) -> list[Any]:
        ...


class CorpusLoaderPort(Protocol):
    """Protocol for loading evaluation corpus test cases."""

    def load_corpus(self, split: str = "all") -> Sequence[Any]:
        ...


def sanitize_case_for_model_input(case: Any) -> dict[str, Any]:
    """Strip all ground truth annotations, gold labels, and reviewer rationales.

    Guarantees gold labels never leak into model prompts or context selection.
    """
    return {
        "case_id": case.case_id,
        "canonical_job_id": case.canonical_job_id,
        "posting_revision": case.posting_revision,
        "posting": case.posting,
        "profile": case.profile,
        "policy": case.policy,
        # NOTICE: gold_label, tags, and reviewer notes are strictly excluded!
    }


def assert_no_publication_authority(obj: Any) -> None:
    """Validate that an execution context or object contains zero Salesforce publication authority."""
    for attr in ("salesforce_client", "salesforce_gateway", "sync_service", "outbox_repository"):
        if hasattr(obj, attr) and getattr(obj, attr) is not None:
            raise PublicationAttemptBlockedError(
                f"Evaluation component contains unauthorized publication attribute '{attr}'. "
                "Publication from evaluation is strictly forbidden."
            )

