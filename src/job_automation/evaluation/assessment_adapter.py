"""Execution adapter running single evaluation arm under strict comparison controls (EVAL-01-S04).

Enforces:
- Deterministic baseline evaluation executed with full decision trace.
- Hard failure precedence (Precedence 1): deterministic rejects complete with zero model calls.
- Comparison mode explicitly passed to AssessorV2 (assessment_mode=AssessmentMode.COMPARISON).
- Capture of proposal, traces, latencies, tokens, and classified errors.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from job_automation.assessment.llm_records import (
    AssessmentLimits,
    AssessmentRequest,
    AssessmentRunResult,
)
from job_automation.assessment.service import AssessmentService
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import (
    AssessmentDisposition,
    AssessmentMode,
    ContextStrategy,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import AssessorV2
from job_automation.evaluation.capture import extract_arm_trace_data
from job_automation.evaluation.records import (
    ArmAttempt,
    EvaluationCase,
    ExperimentManifest,
)
from job_automation.evaluation.timing import StageTimer


class EvaluationArmAdapter:
    """Executes a single context strategy arm for a frozen evaluation case."""

    def __init__(
        self,
        assessment_service: AssessmentService,
        llm_assessor: AssessorV2 | None = None,
    ) -> None:
        self.assessment_service = assessment_service
        self.llm_assessor = llm_assessor

    def execute_arm(
        self,
        case: EvaluationCase,
        manifest: ExperimentManifest,
        strategy: ContextStrategy,
        repetition_index: int,
        pair_id: uuid.UUID,
        baseline: Assessment,
        trace: Any,
        allow_diagnostic_model_call: bool = False,
    ) -> ArmAttempt:
        """Execute one evaluation arm and return a typed ArmAttempt."""
        timer = StageTimer()
        start_time = time.perf_counter()

        # Hard failure precedence: if deterministic rules rejected, skip model call
        if trace.has_rejection() and not allow_diagnostic_model_call:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            timer.timings_ms["total_ms"] = round(elapsed, 2)
            return ArmAttempt(
                pair_id=pair_id,
                case_id=case.case_id,
                strategy=strategy,
                repetition_index=repetition_index,
                execution_status="success",
                final_assessment=baseline,
                stage_latencies_ms=timer.timings_ms,
                captured_trace={
                    "is_deterministic_reject": True,
                    "hard_reasons": trace.confirmed_hard_failures + trace.missing_data_rejections,
                },
            )

        if self.llm_assessor is None:
            # Model assessor not provided (e.g. deterministic-only test or missing model)
            elapsed = (time.perf_counter() - start_time) * 1000.0
            timer.timings_ms["total_ms"] = round(elapsed, 2)
            return ArmAttempt(
                pair_id=pair_id,
                case_id=case.case_id,
                strategy=strategy,
                repetition_index=repetition_index,
                execution_status="failed",
                error=ClassifiedError.from_category(
                    ErrorCategory.MISSING_CONFIGURATION,
                    "LLM assessor not configured for evaluation run",
                ),
                stage_latencies_ms=timer.timings_ms,
            )

        # Build explicit comparison request
        request = AssessmentRequest(
            canonical_job_id=case.canonical_job_id,
            posting_revision=case.posting_revision,
            posting=case.posting,
            profile=case.profile,
            policy=case.policy,
            deterministic_baseline=baseline,
            deterministic_trace=trace,
            context_strategy=strategy,
            purpose="assessment",
            model_identifier=manifest.model_identifier,
            model_digest=manifest.model_digest,
            prompt_version=manifest.prompt_version,
            assessment_mode=AssessmentMode.COMPARISON,  # EXPLICIT COMPARISON MODE
            limits=AssessmentLimits(
                context_limit=manifest.context_limit,
                output_reserve=manifest.output_reserve,
                safety_allowance=manifest.safety_allowance,
            ),
            retrieval_settings=manifest.rag_retrieval_settings if strategy == ContextStrategy.RAG else None,
            extractor_mode=manifest.extractor_mode,
        )

        with timer.time_stage("inference"):
            run_res = self.llm_assessor.assess(request)

        elapsed = (time.perf_counter() - start_time) * 1000.0
        timer.timings_ms["total_ms"] = round(elapsed, 2)

        captured_trace = extract_arm_trace_data(run_res)

        if run_res.status == "success":
            assert run_res.assessment is not None
            return ArmAttempt(
                pair_id=pair_id,
                case_id=case.case_id,
                strategy=strategy,
                repetition_index=repetition_index,
                execution_status="success",
                final_assessment=run_res.assessment,
                stage_latencies_ms=timer.timings_ms,
                captured_trace=captured_trace,
                input_fingerprint=run_res.input_fingerprint,
            )

        # Pending or failed outcome
        execution_status = "failed"
        if run_res.failed_stage == "context_selection":
            execution_status = "overflow"
        elif run_res.status == "pending":
            execution_status = "pending"

        return ArmAttempt(
            pair_id=pair_id,
            case_id=case.case_id,
            strategy=strategy,
            repetition_index=repetition_index,
            execution_status=execution_status,
            error=run_res.error,
            validation_issues=run_res.validation_issues,
            stage_latencies_ms=timer.timings_ms,
            captured_trace=captured_trace,
            input_fingerprint=run_res.input_fingerprint,
        )
