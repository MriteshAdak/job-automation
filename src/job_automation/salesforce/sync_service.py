"""SYNC-01 publication planning and atomic outbox service (SYNC-01-S04).

Enforces:
- Atomic assessment and plan persistence (T1)
- Explicit publication eligibility: initial publication limited to eligible/review
- Continued updates for tracked jobs (even if now rejected or closed)
- Rejection suppression for new unconfirmed jobs
- Per-entity sequence allocation and deterministic fingerprinting
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from typing import TYPE_CHECKING

from job_automation.contracts.enums import (
    AssessmentDisposition,
    PostingAvailability,
    SyncOperationState,
)
from job_automation.contracts.sync import SyncOperation
from job_automation.salesforce.sync_errors import (
    StaleSelectionError,
    SyncMappingError,
    SyncValidationError,
)
from job_automation.salesforce.sync_mapping import (
    build_company_external_id,
    build_company_payload,
    build_job_external_id,
    build_job_payload,
    build_sync_payload,
)
from job_automation.salesforce.sync_ports import SyncServicePort
from job_automation.salesforce.sync_records import (
    EntityType,
    PublicationDecision,
    PublicationPurpose,
    SyncPlan,
    SyncPlanResult,
    SyncStepState,
    SyncSubmission,
    SyncWriteStep,
)
from job_automation.salesforce.sync_serialization import (
    calculate_plan_fingerprint,
    calculate_step_fingerprint,
    serialize_canonical_json,
)
from job_automation.salesforce.sync_settings import SyncMappingConfig

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class SyncService(SyncServicePort):
    """Production implementation of SyncServicePort."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def register_selection_token(
        self,
        canonical_job_id: uuid.UUID,
        generation_token: str,
    ) -> None:
        """Register or advance the active input-generation token for a job."""
        if not generation_token or not generation_token.strip():
            raise SyncValidationError("Generation token must be a non-empty string")
        self.engine.sync_state.register_selection_token(canonical_job_id, generation_token.strip())

    def commit_assessment_and_plan(
        self,
        submission: SyncSubmission,
        config: SyncMappingConfig,
    ) -> SyncPlanResult:
        """Atomically persist assessment and evaluate/enqueue publication plan."""
        # 1. Validate selection generation token against active token (if registered)
        active_token = self.engine.sync_state.get_selection_token(submission.canonical_job_id)
        if active_token is not None and active_token != submission.generation_token:
            # Late result from an older registered generation cannot become current
            raise StaleSelectionError(
                f"Submission generation token '{submission.generation_token}' "
                f"is stale; active generation is '{active_token}'"
            )
        elif active_token is None:
            # Auto-register if not previously explicitly set
            self.register_selection_token(submission.canonical_job_id, submission.generation_token)

        # Check if identical submission (same assessment and generation token) already has a persisted plan (lost response recovery)
        existing_plan = self.engine.sync_state.get_plan_by_assessment(
            submission.canonical_job_id,
            submission.assessment.assessment_id,
        )
        if existing_plan is not None and existing_plan.selection_token == submission.generation_token:
            is_published = existing_plan.publication_decision in (
                PublicationDecision.PUBLISH_INITIAL,
                PublicationDecision.UPDATE_TRACKED,
            )
            sync_op = None
            if is_published:
                for st in existing_plan.steps:
                    if st.operation_id:
                        sync_op = self.engine.sync_state.get_sync_operation(st.operation_id)
                        break
            return SyncPlanResult(
                plan=existing_plan,
                sync_operation=sync_op,
                is_published=is_published,
                publication_decision=existing_plan.publication_decision,
            )

        # 2. Check if job is already tracked remotely
        existing_job_mapping = self.engine.sync_state.get_remote_mapping(
            org_id=config.expected_org_id,
            target_object=config.job_object,
            entity_id=submission.canonical_job_id,
        )
        is_tracked = existing_job_mapping is not None

        # 3. Determine publication decision
        disposition = submission.assessment.final_disposition
        if submission.publication_purpose != PublicationPurpose.PRIMARY_FINAL:
            decision = PublicationDecision.LOCAL_ONLY_COMPARISON
        elif is_tracked:
            # Tracked jobs continue to receive updates even when rejected or unavailable
            decision = PublicationDecision.UPDATE_TRACKED
        else:
            # New job never yet published
            if disposition in (AssessmentDisposition.ELIGIBLE, AssessmentDisposition.REVIEW):
                decision = PublicationDecision.PUBLISH_INITIAL
            else:
                decision = PublicationDecision.LOCAL_ONLY_REJECTED

        # 4. Handle local-only decisions (no outbound write steps)
        if decision in (PublicationDecision.LOCAL_ONLY_REJECTED, PublicationDecision.LOCAL_ONLY_COMPARISON):
            plan_id = uuid.uuid4()
            plan_fingerprint = hashlib.sha256(
                f"{submission.canonical_job_id}:{config.compute_hash()}:{decision.value}:{submission.posting_revision}".encode("utf-8")
            ).hexdigest()

            plan = SyncPlan(
                plan_id=plan_id,
                canonical_job_id=submission.canonical_job_id,
                assessment_id=submission.assessment.assessment_id,
                mapping_version=config.mapping_version,
                mapping_hash=config.compute_hash(),
                plan_fingerprint=plan_fingerprint,
                selection_token=submission.generation_token,
                run_id=submission.run_id,
                publication_decision=decision,
                created_at=datetime.now(timezone.utc),
                steps=[],
            )

            # Persist assessment and plan atomically
            self.engine.sync_state.commit_plan_and_steps(
                plan=plan,
                sync_op=None,
                assessment=submission.assessment,
            )

            return SyncPlanResult(
                plan=plan,
                sync_operation=None,
                is_published=False,
                publication_decision=decision,
            )

        # 5. Publication required: validate required canonical identity
        if submission.canonical_company_id is None:
            raise SyncMappingError(
                f"Cannot publish job {submission.canonical_job_id} without stable canonical_company_id"
            )

        # 6. Allocate per-entity sequence numbers
        job_seq = self.engine.sync_state.allocate_sequence(
            org_id=config.expected_org_id,
            target_object=config.job_object,
            entity_id=submission.canonical_job_id,
        )

        job_marker = f"sync-job-{submission.canonical_job_id}-{job_seq}-{uuid.uuid4().hex[:8]}"
        plan_id = uuid.uuid4()
        operation_id = uuid.uuid4()
        steps: list[SyncWriteStep] = []

        # 7. Resolve Company write step or existing acknowledged mapping
        existing_company_mapping = self.engine.sync_state.get_remote_mapping(
            org_id=config.expected_org_id,
            target_object=config.company_object,
            entity_id=submission.canonical_company_id,
        )

        company_sf_id: str | None = None
        depends_on_step_id: uuid.UUID | None = None

        if existing_company_mapping is not None:
            # Company already acknowledged remotely; reuse remote record ID without replaying
            company_sf_id = existing_company_mapping.salesforce_id
        else:
            # Must upsert Company before Job
            comp_seq = self.engine.sync_state.allocate_sequence(
                org_id=config.expected_org_id,
                target_object=config.company_object,
                entity_id=submission.canonical_company_id,
            )
            comp_marker = f"sync-comp-{submission.canonical_company_id}-{comp_seq}-{uuid.uuid4().hex[:8]}"
            comp_ext_id = build_company_external_id(submission.canonical_company_id)
            comp_payload = build_company_payload(
                submission=submission,
                config=config,
                sequence_number=comp_seq,
                marker=comp_marker,
            )
            comp_step_id = uuid.uuid4()
            comp_fingerprint = calculate_step_fingerprint(
                target_object=config.company_object,
                external_id_field=config.company_external_id_field,
                external_id_value=comp_ext_id,
                sequence_number=comp_seq,
                payload=comp_payload,
            )

            comp_step = SyncWriteStep(
                step_id=comp_step_id,
                plan_id=plan_id,
                operation_id=None,
                entity_type=EntityType.COMPANY,
                entity_id=submission.canonical_company_id,
                sequence_number=comp_seq,
                target_object=config.company_object,
                external_id_field=config.company_external_id_field,
                external_id_value=comp_ext_id,
                relationship_field=None,
                depends_on_step_id=None,
                frozen_payload=comp_payload,
                step_fingerprint=comp_fingerprint,
                state=SyncStepState.PENDING,
                may_have_been_sent=False,
                reconciliation_marker=comp_marker,
            )
            steps.append(comp_step)
            depends_on_step_id = comp_step_id

        # 8. Build Job write step
        job_ext_id = build_job_external_id(submission.canonical_job_id)
        job_payload = build_job_payload(
            submission=submission,
            config=config,
            sequence_number=job_seq,
            marker=job_marker,
            company_salesforce_id=company_sf_id,
        )
        job_step_id = uuid.uuid4()
        job_fingerprint = calculate_step_fingerprint(
            target_object=config.job_object,
            external_id_field=config.job_external_id_field,
            external_id_value=job_ext_id,
            sequence_number=job_seq,
            payload=job_payload,
        )

        job_step = SyncWriteStep(
            step_id=job_step_id,
            plan_id=plan_id,
            operation_id=operation_id,
            entity_type=EntityType.JOB,
            entity_id=submission.canonical_job_id,
            sequence_number=job_seq,
            target_object=config.job_object,
            external_id_field=config.job_external_id_field,
            external_id_value=job_ext_id,
            relationship_field=config.job_company_lookup_field,
            depends_on_step_id=depends_on_step_id,
            frozen_payload=job_payload,
            step_fingerprint=job_fingerprint,
            state=SyncStepState.PENDING,
            may_have_been_sent=False,
            reconciliation_marker=job_marker,
        )
        steps.append(job_step)

        # 9. Build canonical C12 SyncPayload and SyncOperation
        sync_payload = build_sync_payload(submission)
        c12_raw = serialize_canonical_json(sync_payload.model_dump(mode="json"))
        c12_fingerprint = hashlib.sha256(c12_raw).hexdigest()

        sync_op = SyncOperation(
            operation_id=operation_id,
            canonical_job_id=submission.canonical_job_id,
            payload_version=str(job_seq),
            payload_fingerprint=c12_fingerprint,
            locally_owned_payload=sync_payload,
            attempt_count=0,
            max_attempts=3,
            state=SyncOperationState.PENDING,
        )

        # 10. Assemble complete plan
        step_fps = [s.step_fingerprint for s in steps]
        plan_fingerprint = calculate_plan_fingerprint(
            canonical_job_id=str(submission.canonical_job_id),
            mapping_hash=config.compute_hash(),
            step_fingerprints=step_fps,
        )

        plan = SyncPlan(
            plan_id=plan_id,
            canonical_job_id=submission.canonical_job_id,
            assessment_id=submission.assessment.assessment_id,
            mapping_version=config.mapping_version,
            mapping_hash=config.compute_hash(),
            plan_fingerprint=plan_fingerprint,
            selection_token=submission.generation_token,
            run_id=submission.run_id,
            publication_decision=decision,
            created_at=datetime.now(timezone.utc),
            steps=steps,
        )

        # 11. Atomic commit of assessment, C12 operation, plan, and write steps (T1)
        self.engine.sync_state.commit_plan_and_steps(
            plan=plan,
            sync_op=sync_op,
            assessment=submission.assessment,
        )

        return SyncPlanResult(
            plan=plan,
            sync_operation=sync_op,
            is_published=True,
            publication_decision=decision,
        )

    def queue_tracked_refresh(
        self,
        canonical_job_id: uuid.UUID,
        new_availability: PostingAvailability,
        change_token: str,
        config: SyncMappingConfig,
        run_id: str | None = None,
    ) -> SyncPlanResult:
        """Queue updated availability/source facts for an already tracked job."""
        latest_asm = self.engine.assessments.get_latest_assessment(canonical_job_id)
        if latest_asm is None:
            raise SyncValidationError(
                f"Cannot queue refresh: no assessment found for job {canonical_job_id}"
            )

        # Query evaluation timestamp from assessments table
        cursor = self.engine.conn.execute(
            "SELECT created_at FROM assessments WHERE assessment_id = ?",
            (str(latest_asm.assessment_id),),
        )
        row = cursor.fetchone()
        eval_time = (
            datetime.fromisoformat(row["created_at"])
            if row and row["created_at"]
            else datetime.now(timezone.utc)
        )

        canonical_job = self.engine.canonical_jobs.get_canonical_job(canonical_job_id)
        company_name = canonical_job.company_name if canonical_job else "Unknown Employer"
        company_id = canonical_job.canonical_company_id if canonical_job else None

        # Re-use complete selected assessment with new availability snapshot
        submission = SyncSubmission(
            assessment=latest_asm,
            canonical_job_id=canonical_job_id,
            posting_revision=latest_asm.posting_revision,
            evaluated_at=eval_time,  # Preserves original evaluation timestamp
            generation_token=change_token,
            run_id=run_id,
            publication_purpose=PublicationPurpose.PRIMARY_FINAL,
            job_title=getattr(canonical_job, "job_title", "Job Vacancy") if canonical_job else "Job Vacancy",
            company_name=company_name,
            canonical_company_id=company_id,
            source_urls=[],
            availability=new_availability,
        )

        # Register / advance active selection token for this refresh
        self.register_selection_token(canonical_job_id, change_token)

        return self.commit_assessment_and_plan(submission, config)
