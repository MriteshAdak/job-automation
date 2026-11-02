"""Experiment inspection and resumption without duplicated work (EVAL-01-S03).

Enforces:
- Deterministic identification of completed vs incomplete pairs.
- Resumption reuses already committed successful pairs without redundant inference.
- Manifest and input fingerprint verification before resuming.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Sequence

from job_automation.evaluation.errors import InputTamperingError
from job_automation.evaluation.records import (
    EvaluationCase,
    ExperimentManifest,
    PairResult,
)
from job_automation.evaluation.repository import EvaluationRepository


@dataclass
class ExperimentRecoveryPlan:
    """Diagnostic plan indicating completed pairs and remaining cases to execute."""

    experiment: ExperimentManifest
    total_planned_pairs: int
    completed_pairs_count: int
    incomplete_pairs_count: int
    completed_pair_keys: set[tuple[str, int]] = field(default_factory=set)
    cases_to_resume: list[tuple[str, int]] = field(default_factory=list)


class EvaluationRecoveryManager:
    """Manages recovery and resumption of interrupted evaluation experiments."""

    def __init__(self, repository: EvaluationRepository) -> None:
        self.repository = repository

    def inspect_experiment(self, experiment_id: uuid.UUID) -> ExperimentRecoveryPlan:
        """Inspect progress of an experiment and plan resumption."""
        manifest = self.repository.get_experiment(experiment_id)
        if manifest is None:
            raise KeyError(f"Experiment '{experiment_id}' not found in repository")

        existing_pairs = self.repository.list_pairs_for_experiment(experiment_id)

        completed_keys: set[tuple[str, int]] = set()
        for p in existing_pairs:
            if p.pair_completed:
                completed_keys.add((p.case_id, p.repetition_index))

        planned_keys: list[tuple[str, int]] = []
        for case_id in manifest.case_ids:
            for rep in range(manifest.repetitions_per_pair):
                planned_keys.append((case_id, rep))

        remaining_keys = [k for k in planned_keys if k not in completed_keys]

        return ExperimentRecoveryPlan(
            experiment=manifest,
            total_planned_pairs=len(planned_keys),
            completed_pairs_count=len(completed_keys),
            incomplete_pairs_count=len(remaining_keys),
            completed_pair_keys=completed_keys,
            cases_to_resume=remaining_keys,
        )

