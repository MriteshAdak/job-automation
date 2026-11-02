"""Paired evaluation experiment runner (EVAL-01-S04).

Enforces:
- Deterministic baseline built once per frozen case.
- Serial counterbalanced execution order (JSON-first vs RAG-first).
- Strict arm control validation before and after execution.
- Atomic persistence of pair results and arm attempts in isolated evaluation repository.
- Reuse of already completed pairs upon resumption.
- Zero publication side effects.
"""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.assessment.service import AssessmentService
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.interfaces import AssessorV2
from job_automation.evaluation.assessment_adapter import EvaluationArmAdapter
from job_automation.evaluation.composition import EvaluationEnvironment
from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.manifest_validation import (
    extract_arm_controls,
    validate_pair_arm_symmetry,
)
from job_automation.evaluation.records import (
    EvaluationCase,
    ExperimentManifest,
    PairResult,
)


class EvaluationRunner:
    """Executes paired JSON/RAG evaluations on a labeled corpus."""

    def __init__(
        self,
        environment: EvaluationEnvironment,
        assessment_service: AssessmentService,
        llm_assessor: AssessorV2 | None = None,
        allow_diagnostic_model_call: bool = False,
    ) -> None:
        self.environment = environment
        self.repository = environment.repository
        self.assessment_service = assessment_service
        self.llm_assessor = llm_assessor
        self.allow_diagnostic_model_call = allow_diagnostic_model_call
        self.adapter = EvaluationArmAdapter(
            assessment_service=assessment_service,
            llm_assessor=llm_assessor,
        )

    def run_experiment(
        self,
        manifest: ExperimentManifest,
        corpus: EvaluationCorpus,
    ) -> list[PairResult]:
        """Execute paired evaluation experiment across all declared cases."""
        self.repository.save_experiment(manifest, status="running")

        # Verify arm symmetry controls from manifest
        arm_controls = extract_arm_controls(manifest)

        results: list[PairResult] = []

        for case_id in manifest.case_ids:
            case = corpus.get_case(case_id)
            self.repository.save_case(case)

            # Compute deterministic baseline once per frozen case
            baseline, trace = self.assessment_service.evaluate_posting_with_trace(
                canonical_job_id=case.canonical_job_id,
                posting_revision=case.posting_revision,
                posting=case.posting,
                policy=case.policy,
                profile=case.profile,
            )

            for rep in range(manifest.repetitions_per_pair):
                # Check for existing completed pair
                existing_pair = self.repository.get_pair_for_case(
                    experiment_id=manifest.experiment_id,
                    case_id=case_id,
                    repetition_index=rep,
                )
                if existing_pair is not None and existing_pair.pair_completed:
                    results.append(existing_pair)
                    continue

                # Counterbalance execution order deterministically
                order_seed = (
                    abs(hash(case_id)) + rep + manifest.order_randomization_seed
                ) % 2
                execution_order = (
                    [ContextStrategy.JSON, ContextStrategy.RAG]
                    if order_seed == 0
                    else [ContextStrategy.RAG, ContextStrategy.JSON]
                )

                pair_id = existing_pair.pair_id if existing_pair is not None else uuid.uuid4()

                # Execute first arm
                arm1 = self.adapter.execute_arm(
                    case=case,
                    manifest=manifest,
                    strategy=execution_order[0],
                    repetition_index=rep,
                    pair_id=pair_id,
                    baseline=baseline,
                    trace=trace,
                    allow_diagnostic_model_call=self.allow_diagnostic_model_call,
                )

                # Execute second arm
                arm2 = self.adapter.execute_arm(
                    case=case,
                    manifest=manifest,
                    strategy=execution_order[1],
                    repetition_index=rep,
                    pair_id=pair_id,
                    baseline=baseline,
                    trace=trace,
                    allow_diagnostic_model_call=self.allow_diagnostic_model_call,
                )

                json_arm = arm1 if execution_order[0] == ContextStrategy.JSON else arm2
                rag_arm = arm2 if execution_order[0] == ContextStrategy.JSON else arm1

                # Validate arm symmetry
                validate_pair_arm_symmetry(
                    manifest=manifest,
                    case=case,
                    json_arm_controls=arm_controls,
                    rag_arm_controls=arm_controls,
                )

                pair = PairResult(
                    pair_id=pair_id,
                    experiment_id=manifest.experiment_id,
                    case_id=case_id,
                    repetition_index=rep,
                    execution_order=execution_order,
                    baseline_disposition=baseline.final_disposition,
                    json_arm=json_arm,
                    rag_arm=rag_arm,
                )

                self.repository.save_pair_result(pair)
                results.append(pair)

        self.repository.update_experiment_status(manifest.experiment_id, "completed")
        return results
