"""Core coordinator service for AUTO-02 automatic drafting.

Manages:
- Bounded evaluation runs with explicit preview (dry-run) mode.
- Single-worker deployment lock acquisition (WindowsWorkerLock).
- Restart reconciliation of prior unacknowledged/uncertain intents.
- Pure evaluation, deterministic ranking, deduplication, and volume limits.
- Atomic reservation commit followed by idempotent request publication.
- Formatting and returning inspectable evaluation reports.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.contracts.enums import (
    AssessmentDisposition,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.automatic.budgets import BudgetManager
from job_automation.generation.automatic.evaluator import AutomaticDraftEvaluator
from job_automation.generation.automatic.history import DeduplicationManager
from job_automation.generation.automatic.ports import (
    CandidateControlObserver,
    CandidateReader,
)
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftDecision,
    AutomaticDraftEvaluationReport,
    AutomaticDraftIntent,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    AutomaticDraftReservation,
    ReservationStatus,
    SubmissionState,
)
from job_automation.generation.automatic.request_publisher import (
    AutomaticRequestPublisher,
)
from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import LockToken, WindowsWorkerLock
from job_automation.storage.connection import transaction
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class DefaultCandidateReader(CandidateReader):
    """Reads candidate evaluation envelopes directly from local StorageEngine."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def read_candidate_envelope(
        self,
        canonical_job_id: uuid.UUID,
        candidate_id: uuid.UUID,
        org_id: str,
    ) -> tuple[AutomaticDraftCandidate | None, ClassifiedError | None]:
        sel = self.engine.pipeline_work.get_active_selection(canonical_job_id, purpose="assessment")
        if sel is None:
            return None, ClassifiedError.validation(f"No active assessment selection for job {canonical_job_id}")

        assessment = self.engine.assessments.get_assessment(sel.assessment_id)
        if assessment is None:
            return None, ClassifiedError.validation(f"Assessment {sel.assessment_id} not found in storage")

        job = self.engine.canonical_jobs.get_canonical_job(canonical_job_id)
        if job is None:
            return None, ClassifiedError.validation(f"Canonical job {canonical_job_id} not found in storage")

        # Get latest posting revision
        revisions = self.engine.canonical_jobs.list_revisions(canonical_job_id)
        latest_rev = revisions[-1] if revisions else None
        rev_id = str(latest_rev.revision_id) if latest_rev else "rev-default"
        rev_hash = latest_rev.content_hash if latest_rev else "hash-default"

        # Get posting binding or material content hash
        norm_hash = rev_hash
        binding_rec = self.engine.pipeline_work.get_posting_binding(canonical_job_id)
        if binding_rec is not None:
            norm_hash = binding_rec.normalized_content_hash

        # Get profile
        profile = self.engine.profiles.get_profile(candidate_id)
        prof_version = profile.profile_version if profile else "prof-v1"
        prof_digest = profile.content_digest if profile else "digest-default"

        # Get availability
        c_job = self.engine.canonical_jobs.get_canonical_job(canonical_job_id)
        avail_status = c_job.availability if c_job else PostingAvailability.UNKNOWN
        avail_observed = c_job.last_seen_at if c_job else datetime.now(timezone.utc)
        source_states = self.engine.availability.list_for_canonical_job(canonical_job_id)
        if source_states:
            from job_automation.identity.availability.aggregate import aggregate_canonical_availability
            avail_status, _ = aggregate_canonical_availability(source_states)

        # Get candidate control state
        cand_state: str | None = "New"
        cand_opted_out = False
        control_observed = datetime.now(timezone.utc)
        sync_state = self.engine.sync_state.get_candidate_state(canonical_job_id)
        if sync_state is not None:
            cand_state = sync_state.application_status or "New"
            cand_opted_out = getattr(sync_state, "opted_out", False)

        env = AutomaticDraftCandidate(
            candidate_id=candidate_id,
            salesforce_org_id=org_id,
            canonical_job_id=canonical_job_id,
            assessment_id=sel.assessment_id,
            assessment_input_fingerprint=sel.input_fingerprint,
            assessment_disposition=assessment.final_disposition,
            assessment_method=assessment.assessment_method,
            relevance_score=assessment.relevance_score,
            score_scale=assessment.score_scale or "0-100",
            evaluated_at=sel.evaluated_at,
            posting_revision_id=rev_id,
            posting_revision_hash=rev_hash,
            normalized_content_hash=norm_hash,
            profile_version=prof_version,
            profile_digest=prof_digest,
            profile_snapshot=profile,
            search_policy_version=assessment.policy_version or "v1.0",
            search_policy_hash="search_hash",
            availability_status=avail_status,
            availability_observed_at=avail_observed,
            candidate_application_state=cand_state,
            candidate_opted_out=cand_opted_out,
            candidate_control_observed_at=control_observed,
            is_authoritative_selection=sel.is_selected_final,
            identified_unknowns=getattr(assessment, "identified_unknowns", []),
            validation_issues=getattr(assessment, "validation_issues", []),
            rule_coverage_complete=True,
        )
        return env, None


class AutomaticDraftService:
    """Coordinates automatic drafting evaluation, reservation, and publication."""

    def __init__(
        self,
        engine: StorageEngine,
        candidate_reader: CandidateReader | None = None,
        publisher: AutomaticRequestPublisher | None = None,
    ) -> None:
        self.engine = engine
        self.candidate_reader = candidate_reader or DefaultCandidateReader(engine)
        self.publisher = publisher or AutomaticRequestPublisher(engine)
        self.evaluator = AutomaticDraftEvaluator()
        self.dedup_manager = DeduplicationManager(engine)
        self.budget_manager = BudgetManager(engine)

    def evaluate_and_process(
        self,
        policy: AutomaticDraftPolicy,
        candidates: list[AutomaticDraftCandidate] | None = None,
        run_id: uuid.UUID | None = None,
        preview: bool = False,
        now: datetime | None = None,
    ) -> AutomaticDraftEvaluationReport:
        """Execute a bounded automatic drafting evaluation cycle.

        If preview is True, computes decisions and volume feasibility with zero database writes.
        If preview is False, acquires single-worker deployment lock, commits decisions and reservations,
        and publishes admitted requests through GEN-01.
        """
        now_utc = now or datetime.now(timezone.utc)
        exec_run_id = run_id or uuid.uuid4()

        # If candidates not provided, load candidates for all canonical jobs in DB
        if candidates is None:
            candidates = self._load_all_candidates(policy)

        report = AutomaticDraftEvaluationReport(
            run_id=exec_run_id,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            evaluated_at=now_utc,
            total_candidates_evaluated=len(candidates),
        )

        if not policy.enabled:
            # Policy disabled: evaluate all as DISABLED
            for c in candidates:
                dec = self.evaluator.evaluate(c, policy, now=now_utc, evaluation_run_id=exec_run_id)
                self._record_outcome(report, dec.outcome, job_units=1, req_units=0)
                if not preview:
                    self.engine.automatic_drafts.save_decision(dec)
            return report

        # Lock check in execution mode
        lock_token: LockToken | None = None
        if not preview:
            lock = WindowsWorkerLock(self.engine.filestore.artifacts_dir.parent)
            try:
                lock_token = lock.acquire_lock(
                    owner_kind=OwnerKind.GENERATION,
                    attempt_id=exec_run_id,
                    timeout_seconds=0.1,
                )
            except LockContentionError:
                err_msg = "Deployment lock contention: another worker holds deployment lock."
                report.errors.append(err_msg)
                return report

        try:
            # Step 1: In execution mode, reconcile any prior unresolved intents
            if not preview:
                self._reconcile_prior_intents()

            # Step 2: Evaluate eligibility for each candidate
            admitted_candidates: list[tuple[AutomaticDraftCandidate, AutomaticDraftDecision]] = []
            for candidate in candidates:
                decision = self.evaluator.evaluate(candidate, policy, now=now_utc, evaluation_run_id=exec_run_id)
                if decision.outcome == AutomaticDraftOutcome.ADMITTED:
                    admitted_candidates.append((candidate, decision))
                else:
                    self._record_outcome(report, decision.outcome, job_units=1, req_units=0)
                    if decision.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED:
                        report.held_decisions.append(str(decision.decision_id))
                    if not preview:
                        self.engine.automatic_drafts.save_decision(decision)

            # Step 3: Deterministic candidate ranking
            ranked = self.budget_manager.rank_candidates([c for c, _ in admitted_candidates])
            admitted_map = {c.canonical_job_id: d for c, d in admitted_candidates}

            # Step 4: Evaluate deduplication and quotas per candidate bundle
            bundle_units = len(policy.document_variants)

            for candidate in ranked:
                orig_decision = admitted_map[candidate.canonical_job_id]

                # Check deduplication for all variants in bundle
                variant_dedup_results = [
                    self.dedup_manager.check_variant_deduplication(candidate, variant, policy, now=now_utc)
                    for variant in policy.document_variants
                ]

                # If any variant is BLOCKED due to conflict
                conflict_res = next((r for r in variant_dedup_results if r.outcome == AutomaticDraftOutcome.BLOCKED), None)
                if conflict_res is not None:
                    dec = orig_decision.model_copy(
                        update={
                            "outcome": AutomaticDraftOutcome.BLOCKED,
                            "reason_codes": conflict_res.reason_codes,
                            "summary_reason": conflict_res.summary_reason,
                            "existing_intent_key": conflict_res.existing_intent_key,
                        }
                    )
                    self._record_outcome(report, dec.outcome, job_units=1, req_units=0)
                    if not preview:
                        self.engine.automatic_drafts.save_decision(dec)
                    continue

                # If any variant is REVIEW_REQUIRED (e.g. ambiguous manual request)
                review_res = next((r for r in variant_dedup_results if r.outcome == AutomaticDraftOutcome.REVIEW_REQUIRED), None)
                if review_res is not None:
                    dec = orig_decision.model_copy(
                        update={
                            "outcome": AutomaticDraftOutcome.REVIEW_REQUIRED,
                            "reason_codes": review_res.reason_codes,
                            "summary_reason": review_res.summary_reason,
                            "existing_request_id": review_res.existing_request_id,
                        }
                    )
                    self._record_outcome(report, dec.outcome, job_units=1, req_units=0)
                    report.held_decisions.append(str(dec.decision_id))
                    if not preview:
                        self.engine.automatic_drafts.save_decision(dec)
                    continue

                # If all variants are already REUSED (identical inputs already drafted)
                if all(r.outcome == AutomaticDraftOutcome.REUSED for r in variant_dedup_results):
                    reused_keys = [r.client_request_key for r in variant_dedup_results if r.client_request_key]
                    dec = orig_decision.model_copy(
                        update={
                            "outcome": AutomaticDraftOutcome.REUSED,
                            "reason_codes": ["already_drafted_identical_inputs"],
                            "summary_reason": "All selected document variants were already drafted with identical inputs.",
                            "existing_intent_key": reused_keys[0] if reused_keys else None,
                        }
                    )
                    self._record_outcome(report, dec.outcome, job_units=1, req_units=0)
                    report.reused_intents.extend(reused_keys)
                    if not preview:
                        self.engine.automatic_drafts.save_decision(dec)
                    continue

                # If any variant is SUPPRESSED (e.g. first_only already drafted or cooldown)
                suppressed_res = next((r for r in variant_dedup_results if r.outcome == AutomaticDraftOutcome.SUPPRESSED), None)
                if suppressed_res is not None:
                    dec = orig_decision.model_copy(
                        update={
                            "outcome": AutomaticDraftOutcome.SUPPRESSED,
                            "reason_codes": suppressed_res.reason_codes,
                            "summary_reason": suppressed_res.summary_reason,
                            "existing_intent_key": suppressed_res.existing_intent_key,
                            "existing_request_id": suppressed_res.existing_request_id,
                        }
                    )
                    self._record_outcome(report, dec.outcome, job_units=1, req_units=0)
                    if not preview:
                        self.engine.automatic_drafts.save_decision(dec)
                    continue

                # Check bundle volume quota
                quota_check = self.budget_manager.check_bundle_quota(
                    candidate=candidate,
                    policy=policy,
                    bundle_units=bundle_units,
                    evaluation_run_id=exec_run_id,
                    now=now_utc,
                )

                if not quota_check.allowed:
                    # Defer entire bundle atomically
                    dec = orig_decision.model_copy(
                        update={
                            "outcome": AutomaticDraftOutcome.DEFERRED,
                            "reason_codes": ["volume_quota_exhausted"],
                            "summary_reason": quota_check.reason or "Volume quota exhausted.",
                            "quota_snapshot": quota_check.quota_snapshot,
                        }
                    )
                    self._record_outcome(report, dec.outcome, job_units=1, req_units=bundle_units)
                    report.deferred_decisions.append(str(dec.decision_id))
                    if not preview:
                        self.engine.automatic_drafts.save_decision(dec)
                    continue

                # Qualifying candidate with quota available!
                dec = orig_decision.model_copy(
                    update={
                        "outcome": AutomaticDraftOutcome.ADMITTED,
                        "reason_codes": ["eligibility_and_quota_verified"],
                        "summary_reason": "Admitted for automatic request creation.",
                        "quota_snapshot": quota_check.quota_snapshot,
                    }
                )
                self._record_outcome(report, dec.outcome, job_units=1, req_units=bundle_units)

                # Build intents and reservations
                bundle_intents: list[AutomaticDraftIntent] = []
                bundle_reservations: list[AutomaticDraftReservation] = []

                for variant, r in zip(policy.document_variants, variant_dedup_results):
                    intent = AutomaticDraftIntent(
                        client_request_key=r.client_request_key or "",
                        candidate_id=candidate.candidate_id,
                        salesforce_org_id=candidate.salesforce_org_id,
                        canonical_job_id=candidate.canonical_job_id,
                        document_type=variant.document_type,
                        target_language=variant.target_language,
                        template_id=variant.template_id,
                        context_strategy=variant.context_strategy,
                        formats=variant.formats,
                        material_generation_fingerprint=r.material_fingerprint or "",
                        policy_id=policy.policy_id,
                        policy_version=policy.policy_version,
                        policy_content_hash=policy.policy_content_hash or "unhashed",
                        decision_id=dec.decision_id,
                        request_payload_digest=r.payload_digest or "",
                        request_payload_json=r.payload_json or "{}",
                        submission_state=SubmissionState.RESERVED,
                        created_at=now_utc,
                        updated_at=now_utc,
                    )
                    res = AutomaticDraftReservation(
                        candidate_id=candidate.candidate_id,
                        salesforce_org_id=candidate.salesforce_org_id,
                        canonical_job_id=candidate.canonical_job_id,
                        evaluation_run_id=exec_run_id,
                        intent_id=intent.intent_id,
                        client_request_key=intent.client_request_key,
                        document_units=1,
                        status=ReservationStatus.ACTIVE,
                        reserved_at=now_utc,
                    )
                    bundle_intents.append(intent)
                    bundle_reservations.append(res)
                    report.admitted_intents.append(intent.client_request_key)

                if preview:
                    continue

                # Execution mode: Atomically persist policy, decision, intents, and reservations
                with transaction(self.engine.conn):
                    self.engine.automatic_drafts.save_policy(policy)
                    self.engine.automatic_drafts.save_decision(dec)
                    for intent in bundle_intents:
                        self.engine.automatic_drafts.save_intent(intent)
                    for res in bundle_reservations:
                        self.engine.automatic_drafts.save_reservation(res)

                # Outside transaction: publish and bind through admission
                pub_results = self.publisher.publish_bundle(bundle_intents, candidate, policy)
                for intent, req, err in pub_results:
                    if err is not None:
                        report.errors.append(f"Failed to publish intent {intent.client_request_key}: {err.message}")

        finally:
            if lock_token is not None:
                lock_token.release()

        return report

    def _load_all_candidates(self, policy: AutomaticDraftPolicy) -> list[AutomaticDraftCandidate]:
        candidates: list[AutomaticDraftCandidate] = []
        jobs = self.engine.canonical_jobs.list_canonical_jobs()
        for job in jobs:
            env, err = self.candidate_reader.read_candidate_envelope(
                canonical_job_id=job.canonical_job_id,
                candidate_id=policy.candidate_id,
                org_id=policy.salesforce_org_id,
            )
            if env is not None:
                candidates.append(env)
        return candidates

    def _reconcile_prior_intents(self) -> None:
        """Reconcile unacknowledged or uncertain intents from previous interrupted runs."""
        active_intents = self.engine.automatic_drafts.list_active_intents()
        for intent in active_intents:
            if intent.submission_state in (SubmissionState.RESERVED, SubmissionState.SENDING, SubmissionState.UNCERTAIN):
                # Check if matching local request already exists in generation_requests
                existing_c13 = self.engine.generation_requests.get_by_client_key(intent.client_request_key)
                if existing_c13 is not None:
                    # Request was admitted before crash; update intent to ACKNOWLEDGED
                    intent.submission_state = SubmissionState.ACKNOWLEDGED
                    intent.local_request_id = existing_c13.request_id
                    intent.salesforce_request_id = existing_c13.salesforce_request_id
                    self.engine.automatic_drafts.save_intent(intent)

    def _record_outcome(
        self,
        report: AutomaticDraftEvaluationReport,
        outcome: AutomaticDraftOutcome,
        job_units: int,
        req_units: int,
    ) -> None:
        val = outcome.value
        report.jobs_by_outcome[val] = report.jobs_by_outcome.get(val, 0) + job_units
        report.requests_by_outcome[val] = report.requests_by_outcome.get(val, 0) + req_units
