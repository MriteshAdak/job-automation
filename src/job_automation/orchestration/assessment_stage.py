"""Assessment stage coordinator executing deterministic rules and model assessment (RUN-01-S06, S09)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

from job_automation.assessment.models import AssessmentInput
from job_automation.assessment.service import AssessmentService, evaluate_deterministic_with_trace
from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import AssessmentDisposition, PipelineStage
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.errors import MissingComponentError
from job_automation.orchestration.fingerprints import (
    compute_profile_snapshot_fingerprint,
    compute_stage_work_fingerprint,
)
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.records import (
    AssessmentMode,
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.orchestration.selection import SelectionManager
from job_automation.policy.models import EffectivePolicy
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


@dataclass
class AssessmentExecutionItem:
    """Evaluated assessment paired with its posting binding and selection manifest."""

    binding: PostingBinding
    selection: AssessmentSelection
    assessment: Assessment
    is_reused: bool = False


@dataclass
class AssessmentStageExecutionResult:
    """Outcome of assessment stage execution."""

    items: list[AssessmentExecutionItem] = field(default_factory=list)
    eligible_count: int = 0
    review_count: int = 0
    rejected_count: int = 0
    reused_count: int = 0
    pending_items: list[str] = field(default_factory=list)
    total_evaluated: int = 0
    model_invocations_count: int = 0


class AssessmentStageCoordinator:
    """Coordinates deterministic rules and model assessment with input-version invalidation."""

    def __init__(
        self,
        engine: StorageEngine,
        assessment_service: AssessmentService,
        selection_manager: SelectionManager,
        invalidation_evaluator: InvalidationEvaluator,
        llm_assessor: Any | None = None,
    ) -> None:
        self.engine = engine
        self.assessment_service = assessment_service
        self.selection_manager = selection_manager
        self.invalidation_evaluator = invalidation_evaluator
        self.llm_assessor = llm_assessor
        self.checkpoint_coord = CheckpointCoordinator(engine)

    def execute_assessment(
        self,
        request: RunRequest,
        attempt: RunAttempt,
        bindings: Sequence[PostingBinding],
        profile: ProfileSnapshot,
        policy: EffectivePolicy | SearchPolicy,
        model_identifier: str | None = None,
        prompt_version: str | None = "v1",
    ) -> AssessmentStageExecutionResult:
        """Assess all bindings with input invalidation and authoritative selection."""
        run_id = request.run_id
        self.checkpoint_coord.record_stage_start(run_id, "assess")

        items: list[AssessmentExecutionItem] = []
        eligible_count = 0
        review_count = 0
        rejected_count = 0
        reused_count = 0
        model_invocations_count = 0
        pending_items: list[str] = []

        prof_hash = request.profile_snapshot_hash or compute_profile_snapshot_fingerprint(profile)
        pol_fp = request.policy_fingerprint or (
            str(policy.fingerprint) if hasattr(policy, "fingerprint") else "pol_fp"
        )
        mode_str = request.assessment_mode.value
        strategy_str = request.primary_strategy.value if request.assessment_mode == AssessmentMode.LLM else None

        for binding in bindings:
            can_id = binding.canonical_job_id
            rev_hash = binding.normalized_content_hash

            requires_reassessment, target_fp, active_sel, existing_asmt = (
                self.invalidation_evaluator.check_invalidation(
                    canonical_job_id=can_id,
                    revision_content_hash=rev_hash,
                    profile_snapshot_hash=prof_hash,
                    policy_fingerprint=pol_fp,
                    assessment_mode=mode_str,
                    strategy=strategy_str,
                    model_identifier=model_identifier,
                    prompt_version=prompt_version,
                )
            )

            work_key = f"assess:{can_id}"
            fp = compute_stage_work_fingerprint(
                stage_name="assess",
                work_key=work_key,
                inputs={"target_fp": target_fp},
            )

            if not requires_reassessment and active_sel is not None and existing_asmt is not None:
                # Reuse existing assessment! Zero evaluator calls.
                reused_count += 1
                items.append(
                    AssessmentExecutionItem(
                        binding=binding,
                        selection=active_sel,
                        assessment=existing_asmt,
                        is_reused=True,
                    )
                )
                work = StageWorkRecord(
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                    stage_name="assess",
                    work_key=work_key,
                    input_fingerprint=fp,
                    output_id=str(existing_asmt.assessment_id),
                    state=WorkItemState.COMPLETED,
                    checkpoint_data={"reused": True},
                )
                self.engine.pipeline_work.save_stage_work(work)
                continue

            # Requires new assessment
            gen_token = self.selection_manager.build_generation_token(target_fp)

            # Evaluate deterministic baseline
            asmt_baseline, trace = self.assessment_service.evaluate_posting_with_trace(
                canonical_job_id=can_id,
                posting_revision=rev_hash,
                posting=binding.c06_snapshot,
                policy=policy,
                profile=profile,
                execution_id=run_id,
            )

            final_asmt: Assessment | None = None

            if request.assessment_mode == AssessmentMode.RULES:
                final_asmt = asmt_baseline
            elif request.assessment_mode == AssessmentMode.LLM:
                # Precedence 1: Deterministic confirmed hard failures remain REJECTED
                if asmt_baseline.final_disposition == AssessmentDisposition.REJECTED:
                    final_asmt = asmt_baseline
                else:
                    if self.llm_assessor is None:
                        raise MissingComponentError(
                            "LLM assessment requested (--assessment-mode llm) but MATCH-02 LLMAssessmentService is missing or not configured."
                        )

                    from job_automation.assessment.llm_records import AssessmentLimits, AssessmentRequest

                    llm_req = AssessmentRequest(
                        canonical_job_id=can_id,
                        posting_revision=rev_hash,
                        posting=binding.c06_snapshot,
                        profile=profile,
                        policy=policy,
                        context_strategy=request.primary_strategy,
                        deterministic_baseline=asmt_baseline,
                        deterministic_trace=trace,
                        limits=AssessmentLimits(),
                        model_identifier=model_identifier or "llama3:8b-instruct-q4_K_M",
                        prompt_version=prompt_version or "v1",
                    )

                    model_invocations_count += 1
                    llm_res = self.llm_assessor.assess(llm_req)
                    if llm_res.status == "success" and llm_res.assessment is not None:
                        final_asmt = llm_res.assessment
                    else:
                        # Pending outcome
                        pending_reason = (
                            f"LLM assessment pending for job {can_id} ({llm_res.failed_stage}): "
                            f"{llm_res.error.message if llm_res.error else 'Unknown error'}"
                        )
                        pending_items.append(pending_reason)
                        work = StageWorkRecord(
                            run_id=run_id,
                            attempt_id=attempt.attempt_id,
                            stage_name="assess",
                            work_key=work_key,
                            input_fingerprint=fp,
                            state=WorkItemState.PENDING,
                            error=llm_res.error,
                        )
                        self.engine.pipeline_work.save_stage_work(work)
                        continue

            assert final_asmt is not None

            # Persist C11 assessment and register selection
            self.engine.assessments.save_assessment(final_asmt)
            selection = self.selection_manager.select_and_persist(
                canonical_job_id=can_id,
                candidate_id=profile.candidate_id,
                assessment=final_asmt,
                input_fingerprint=target_fp,
                generation_token=gen_token,
            )

            # Count newly evaluated disposition
            if final_asmt.final_disposition == AssessmentDisposition.ELIGIBLE:
                eligible_count += 1
            elif final_asmt.final_disposition == AssessmentDisposition.REVIEW:
                review_count += 1
            elif final_asmt.final_disposition == AssessmentDisposition.REJECTED:
                rejected_count += 1

            items.append(
                AssessmentExecutionItem(
                    binding=binding,
                    selection=selection,
                    assessment=final_asmt,
                    is_reused=False,
                )
            )

            work = StageWorkRecord(
                run_id=run_id,
                attempt_id=attempt.attempt_id,
                stage_name="assess",
                work_key=work_key,
                input_fingerprint=fp,
                output_id=str(final_asmt.assessment_id),
                state=WorkItemState.COMPLETED,
            )
            self.engine.pipeline_work.save_stage_work(work)

        self.checkpoint_coord.record_stage_complete(
            run_id=run_id,
            stage_name="assess",
            checkpoint_data={
                "eligible_count": eligible_count,
                "review_count": review_count,
                "rejected_count": rejected_count,
                "reused_count": reused_count,
                "pending_count": len(pending_items),
            },
        )

        return AssessmentStageExecutionResult(
            items=items,
            eligible_count=eligible_count,
            review_count=review_count,
            rejected_count=rejected_count,
            reused_count=reused_count,
            pending_items=pending_items,
            total_evaluated=len(items) - reused_count,
            model_invocations_count=model_invocations_count,
        )
