"""PipelineRunner coordinating preflight, locking, recovery, stages, and finalization (RUN-01-S08).

Enforces:
- Exclusive worker process lock via WorkerProcessLock.
- Checkpointed stage transitions with granular recovery.
- Deterministic-first execution, followed by configured LLM execution.
- Honest C15 summaries and companion reporting.
- Clean handle release and state reconciliation across crashes.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from job_automation.assessment.service import AssessmentService
from job_automation.configuration import AppConfig, ResolvedPaths, load_config
from job_automation.contracts.enums import (
    PipelineStage,
    RunStatus,
)
from job_automation.contracts.enums import (
    ContextStrategy,
    PipelineStage,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.profile import ProfileSnapshot
from job_automation.contracts.runs import RunSummary
from job_automation.identity.service import IdentityService
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.availability_stage import AvailabilityStageCoordinator
from job_automation.orchestration.fetch_stage import FetchStageCoordinator
from job_automation.orchestration.fingerprints import compute_profile_snapshot_fingerprint
from job_automation.orchestration.identity_stage import IdentityStageCoordinator
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.errors import LockAccessError, LockContentionError, MissingComponentError
from job_automation.orchestration.llm_stage import build_llm_assessor
from job_automation.orchestration.windows_lock import WindowsWorkerLock as WorkerProcessLock
from job_automation.orchestration.normalize_stage import NormalizeStageCoordinator
from job_automation.orchestration.records import (
    AssessmentMode,
    AssessmentSelection,
    PostingBinding,
    RunAttempt,
    RunRequest,
)
from job_automation.orchestration.recovery import RecoveryManager
from job_automation.orchestration.reporting import RunReport
from job_automation.orchestration.selection import SelectionManager
from job_automation.orchestration.summary import build_run_summary
from job_automation.orchestration.sync_bridge import build_sync_submission
from job_automation.orchestration.sync_stage import SyncStageCoordinator
from job_automation.policy.service import PolicyService
from job_automation.profile.service import ProfileService
from job_automation.salesforce.sync_records import SyncSubmission
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.sources.models import EffectiveSource
from job_automation.sources.service import SourceRegistryService
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class RunOptions:
    """Options and parameters for a pipeline run execution."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        data_root: str | Path | None = None,
        run_config_path: str | Path | None = None,
        resume_run_id: uuid.UUID | None = None,
        assessment_mode: str = "rules",
        llm_strategy: str = "json",
        sources: list[str] | None = None,
        enable_sync: bool = True,
        run_candidate_backup: bool = True,
        sync_config_path: str | Path | None = None,
        gateway: SalesforceGatewayV2 | None = None,
        stop_on_first_error: bool = False,
        json_output: bool = False,
        llm_assessor: Any | None = None,
        model_transport: Any | None = None,
        model_identifier: str | None = None,
        prompt_version: str | None = None,
        trigger_kind: str | None = None,
        schedule_occurrence_id: uuid.UUID | str | None = None,
        slot_key: str | None = None,
        deliver_summary: bool = True,
        summary_target: Any | None = None,
        summary_delivery_settings_path: str | Path | None = None,
    ) -> None:
        self.config_path = config_path
        self.data_root = data_root
        self.run_config_path = run_config_path
        self.resume_run_id = resume_run_id
        self.assessment_mode = assessment_mode.lower()
        self.llm_strategy = llm_strategy.lower()
        self.sources = sources
        self.enable_sync = enable_sync
        self.run_candidate_backup = run_candidate_backup
        self.sync_config_path = sync_config_path
        self.gateway = gateway
        self.stop_on_first_error = stop_on_first_error
        self.json_output = json_output
        self.llm_assessor = llm_assessor
        self.model_transport = model_transport
        self.model_identifier = model_identifier
        self.prompt_version = prompt_version
        self.trigger_kind = trigger_kind
        self.schedule_occurrence_id = schedule_occurrence_id
        self.slot_key = slot_key
        self.deliver_summary = deliver_summary
        self.summary_target = summary_target
        self.summary_delivery_settings_path = summary_delivery_settings_path


class PipelineRunner:
    """Production pipeline runner implementing RUN-01."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        data_root: str | Path | None = None,
        engine: StorageEngine | None = None,
    ) -> None:
        self.config_path = config_path
        self.data_root = data_root
        self._engine = engine
        self._owns_engine = engine is None

    def _get_config_and_paths(self) -> tuple[AppConfig, ResolvedPaths]:
        """Resolve config and paths without opening or migrating database."""
        return load_config(
            config_path=self.config_path,
            data_root_override=self.data_root,
        )

    def _get_engine(self, app_config: AppConfig, paths: ResolvedPaths) -> StorageEngine:
        """Initialize storage engine and apply schema migrations under lock."""
        if self._engine is not None:
            return self._engine
        engine = StorageEngine.from_config(app_config, paths)
        engine.initialize_schema()
        return engine

    def _get_engine_and_paths(self) -> tuple[StorageEngine, ResolvedPaths, AppConfig]:
        """Resolve config, paths, and storage engine."""
        app_config, paths = self._get_config_and_paths()
        engine = self._get_engine(app_config, paths)
        return engine, paths, app_config

    def _finalize_and_record_summary(
        self,
        engine: StorageEngine,
        paths: ResolvedPaths | None,
        opts: RunOptions,
        report: RunReport,
    ) -> RunReport:
        """Record durable completion receipt and optionally dispatch summary delivery without altering pipeline outcome."""
        try:
            from job_automation.orchestration.summary_delivery.service import SummaryDeliveryService
            from job_automation.orchestration.summary_delivery.settings import load_summary_delivery_settings

            settings_path = opts.summary_delivery_settings_path or (paths.summary_delivery_settings_path if paths else None)
            if not settings_path and self.config_path:
                try:
                    from job_automation.configuration import load_config
                    _, loaded_paths = load_config(self.config_path, self.data_root)
                    settings_path = loaded_paths.summary_delivery_settings_path
                except Exception:
                    pass
            sd_settings = load_summary_delivery_settings(settings_path)
            sd_service = SummaryDeliveryService(
                engine=engine,
                settings=sd_settings,
                target_adapter=opts.summary_target,
            )
            # 1. Record terminal completion receipt
            sd_service.record_run_completion(report)

            # 2. If delivery is enabled and requested, attempt bounded delivery
            if sd_settings.enabled and opts.deliver_summary:
                try:
                    sd_service.deliver_summary(run_id=report.c15_summary.run_id)
                except Exception as deliv_exc:
                    logger.warning("Summary delivery dispatch encountered non-fatal error: %s", deliv_exc)
        except Exception as exc:
            logger.warning("Error in summary delivery completion handoff: %s", exc)

        return report

    def start_run(
        self,
        options: RunOptions | None = None,
        profile_override: ProfileSnapshot | None = None,
        policy_override: SearchPolicy | None = None,
        effective_sources_override: list[EffectiveSource] | None = None,
    ) -> RunReport:
        """Execute a new pipeline run."""
        opts = options or RunOptions()
        app_config, paths = self._get_config_and_paths()
        lock = WorkerProcessLock(paths.data_root)

        # 1. Acquire exclusive lock BEFORE opening or migrating database
        token = None
        try:
            token = lock.acquire_lock()
        except LockAccessError as exc:
            # Lock file access denied / permission failure -> exit code 2 (unrecoverable preflight failure)
            summary = build_run_summary(
                run_id=uuid.uuid4(),
                start_time=datetime.now(timezone.utc),
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.PERMISSION,
                        message=f"Pipeline lock access failure on '{paths.data_root}': {exc}",
                        recoverable=False,
                    )
                ],
            )
            return RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=2,
            )
        except LockContentionError as exc:
            # Lock busy -> exit code 3 (zero DB writes)
            summary = build_run_summary(
                run_id=uuid.uuid4(),
                start_time=datetime.now(timezone.utc),
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.CAPACITY,
                        message=f"Pipeline lock busy on '{paths.data_root}': {exc.details.get('holding_pid') or 'another process'} holds lock",
                        recoverable=True,
                    )
                ],
            )
            return RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=3,
            )

        start_time = datetime.now(timezone.utc)
        run_id = uuid.uuid4()
        engine = self._get_engine(app_config, paths)

        try:
            # 2. Preflight verification
            profile = profile_override
            if profile is None:
                prof_svc = ProfileService.from_engine(engine)
                profile = prof_svc.get_current_snapshot()
                if profile is None:
                    summary = build_run_summary(
                        run_id=run_id,
                        start_time=start_time,
                        is_fatal_failure=True,
                        errors=[
                            ClassifiedError(
                                category=ErrorCategory.MISSING_CONFIGURATION,
                                message="Preflight failed: No approved candidate profile snapshot found",
                                recoverable=False,
                            )
                        ],
                    )
                    return RunReport(
                        c15_summary=summary,
                        assessment_mode=opts.assessment_mode,
                        exit_code=2,
                    )

            policy = policy_override
            if policy is None:
                pol_res = PolicyService.load_from_config(self.config_path, self.data_root)
                if not pol_res.is_valid or pol_res.effective_policy is None:
                    summary = build_run_summary(
                        run_id=run_id,
                        start_time=start_time,
                        is_fatal_failure=True,
                        errors=[
                            ClassifiedError(
                                category=ErrorCategory.MISSING_CONFIGURATION,
                                message="Preflight failed: Active search policy is missing or invalid",
                                recoverable=False,
                            )
                        ],
                    )
                    return RunReport(
                        c15_summary=summary,
                        assessment_mode=opts.assessment_mode,
                        exit_code=2,
                    )
                policy = pol_res.effective_policy

            # Resolve sources
            effective_sources = effective_sources_override
            if effective_sources is None:
                src_svc, _, _ = SourceRegistryService.load_from_config(self.config_path, self.data_root)
                if opts.sources:
                    sel_res = src_svc.select_sources(opts.sources)
                    if not sel_res.is_valid:
                        summary = build_run_summary(
                            run_id=run_id,
                            start_time=start_time,
                            is_fatal_failure=True,
                            errors=[
                                ClassifiedError(
                                    category=ErrorCategory.VALIDATION,
                                    message=f"Preflight failed: Selected sources invalid: {sel_res.unmet_keys}",
                                    recoverable=False,
                                )
                            ],
                        )
                        return RunReport(
                            c15_summary=summary,
                            assessment_mode=opts.assessment_mode,
                            exit_code=2,
                        )
                    effective_sources = sel_res.selected_sources
                else:
                    effective_sources = list(src_svc.sources.values())

            # Load sync config
            sync_config: SyncMappingConfig | None = None
            if opts.enable_sync:
                sync_path = opts.sync_config_path or (paths.sync_mapping_path if paths.sync_mapping_path and paths.sync_mapping_path.is_file() else None) or (Path("config") / "sync.example.json")
                if Path(sync_path).is_file():
                    sync_config = load_sync_mapping_config(sync_path)
                else:
                    sync_config = SyncMappingConfig()

            # 3. Register Run and Initial Attempt
            engine.runs.create_run(run_id=run_id, start_time=start_time, status="running")
            req = RunRequest(
                run_id=run_id,
                assessment_mode=AssessmentMode.RULES if opts.assessment_mode == "rules" else AssessmentMode.LLM,
                primary_strategy=ContextStrategy.RAG if opts.llm_strategy == "rag" else ContextStrategy.JSON,
                source_keys=opts.sources,
                app_config_hash=hashlib.sha256(app_config.model_dump_json().encode("utf-8")).hexdigest(),
                policy_fingerprint=str(policy.fingerprint) if hasattr(policy, "fingerprint") else None,
                profile_snapshot_hash=compute_profile_snapshot_fingerprint(profile),
                trigger_kind=opts.trigger_kind,
                schedule_occurrence_id=str(opts.schedule_occurrence_id) if opts.schedule_occurrence_id else None,
                slot_key=opts.slot_key,
            )
            att = RunAttempt(
                run_id=run_id,
                attempt_sequence=1,
                status="running",
            )
            engine.pipeline_work.save_run_request(req)
            engine.pipeline_work.save_run_attempt(att)

            # 4. Execute Stages
            return self._execute_pipeline(
                engine=engine,
                request=req,
                attempt=att,
                start_time=start_time,
                opts=opts,
                profile=profile,
                policy=policy,
                effective_sources=effective_sources,
                sync_config=sync_config,
                app_config=app_config,
                paths=paths,
            )

        except MissingComponentError as exc:
            summary = build_run_summary(
                run_id=run_id,
                start_time=start_time,
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.MISSING_CONFIGURATION,
                        message=str(exc),
                        recoverable=False,
                    )
                ],
            )
            try:
                engine.runs.complete_run(summary)
                att_failed = RunAttempt(
                    run_id=run_id,
                    attempt_sequence=1,
                    status="failed",
                    completed_at=datetime.now(timezone.utc),
                    exit_code=2,
                )
                engine.pipeline_work.save_run_attempt(att_failed)
            except Exception:
                pass
            rep = RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=2,
            )
            return self._finalize_and_record_summary(engine, paths, opts, rep)

        except KeyboardInterrupt:
            summary = build_run_summary(
                run_id=run_id,
                start_time=start_time,
                is_partial=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.VALIDATION,
                        message="Run interrupted by user (SIGINT/Ctrl+C)",
                        recoverable=True,
                    )
                ],
            )
            try:
                engine.runs.complete_run(summary)
                att_interrupted = RunAttempt(
                    run_id=run_id,
                    attempt_sequence=1,
                    status="interrupted",
                    completed_at=datetime.now(timezone.utc),
                    exit_code=130,
                )
                engine.pipeline_work.save_run_attempt(att_interrupted)
            except Exception:
                pass
            rep = RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=130,
            )
            return self._finalize_and_record_summary(engine, paths, opts, rep)

        finally:
            if token is not None:
                token.release()
            if self._owns_engine:
                engine.close()

    def resume_run(
        self,
        run_id: uuid.UUID,
        options: RunOptions | None = None,
        profile_override: ProfileSnapshot | None = None,
        policy_override: SearchPolicy | None = None,
        effective_sources_override: list[EffectiveSource] | None = None,
    ) -> RunReport:
        """Resume an existing pipeline run using persisted checkpoints."""
        opts = options or RunOptions()
        app_config, paths = self._get_config_and_paths()
        lock = WorkerProcessLock(paths.data_root)

        token = None
        try:
            token = lock.acquire_lock()
        except LockAccessError as exc:
            summary = build_run_summary(
                run_id=run_id,
                start_time=datetime.now(timezone.utc),
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.PERMISSION,
                        message=f"Pipeline lock access failure on '{paths.data_root}': {exc}",
                        recoverable=False,
                    )
                ],
            )
            return RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=2,
            )
        except LockContentionError as exc:
            summary = build_run_summary(
                run_id=run_id,
                start_time=datetime.now(timezone.utc),
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.CAPACITY,
                        message=f"Pipeline lock busy on '{paths.data_root}': {exc.details.get('holding_pid') or 'another process'} holds lock",
                        recoverable=True,
                    )
                ],
            )
            return RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=3,
            )

        engine = self._get_engine(app_config, paths)

        try:
            # Reconcile existing run
            rec_mgr = RecoveryManager(engine)
            rec_plan = rec_mgr.reconcile_interrupted_run(run_id)

            # Read frozen request
            req = engine.pipeline_work.get_run_request(run_id)
            if req is None:
                summary = build_run_summary(
                    run_id=run_id,
                    start_time=datetime.now(timezone.utc),
                    is_fatal_failure=True,
                    errors=[
                        ClassifiedError(
                            category=ErrorCategory.VALIDATION,
                            message=f"Run request for '{run_id}' not found",
                            recoverable=False,
                        )
                    ],
                )
                return RunReport(
                    c15_summary=summary,
                    assessment_mode=opts.assessment_mode,
                    exit_code=2,
                )

            att = rec_mgr.create_new_attempt(run_id, sequence=rec_plan.next_attempt_sequence)

            # Resolve domain models
            profile = profile_override or ProfileService.from_engine(engine).get_current_snapshot()
            if profile is None:
                raise ValueError("No approved profile snapshot available for resume")

            policy = policy_override
            if policy is None:
                pol_res = PolicyService.load_from_config(self.config_path, self.data_root)
                policy = pol_res.effective_policy
            if policy is None:
                raise ValueError("No valid search policy available for resume")

            effective_sources = effective_sources_override
            if effective_sources is None:
                src_svc, _, _ = SourceRegistryService.load_from_config(self.config_path, self.data_root)
                if req.source_keys:
                    sel_res = src_svc.select_sources(req.source_keys)
                    if sel_res.is_valid:
                        effective_sources = sel_res.selected_sources
                    else:
                        effective_sources = list(src_svc.sources.values())
                else:
                    effective_sources = list(src_svc.sources.values())

            sync_config = None
            if opts.enable_sync:
                sync_path = opts.sync_config_path or (paths.sync_mapping_path if paths.sync_mapping_path and paths.sync_mapping_path.is_file() else None) or (Path("config") / "sync.example.json")
                if Path(sync_path).is_file():
                    sync_config = load_sync_mapping_config(sync_path)
                else:
                    sync_config = SyncMappingConfig()

            return self._execute_pipeline(
                engine=engine,
                request=req,
                attempt=att,
                start_time=req.created_at,
                opts=opts,
                profile=profile,
                policy=policy,
                effective_sources=effective_sources,
                sync_config=sync_config,
                app_config=app_config,
                paths=paths,
            )

        except MissingComponentError as exc:
            summary = build_run_summary(
                run_id=run_id,
                start_time=datetime.now(timezone.utc),
                is_fatal_failure=True,
                errors=[
                    ClassifiedError(
                        category=ErrorCategory.MISSING_CONFIGURATION,
                        message=str(exc),
                        recoverable=False,
                    )
                ],
            )
            try:
                engine.runs.complete_run(summary)
            except Exception:
                pass
            rep = RunReport(
                c15_summary=summary,
                assessment_mode=opts.assessment_mode,
                exit_code=2,
            )
            return self._finalize_and_record_summary(engine, paths, opts, rep)

        finally:
            if token is not None:
                token.release()
            if self._owns_engine:
                engine.close()

    def show_run(self, run_id: uuid.UUID) -> RunReport | None:
        """Inspect a pipeline run summary in read-only mode."""
        engine, _, _ = self._get_engine_and_paths()
        try:
            summary = engine.runs.get_run(run_id)
            if summary is None:
                return None
            req = engine.pipeline_work.get_run_request(run_id)
            att = engine.pipeline_work.get_latest_attempt(run_id)
            return RunReport(
                c15_summary=summary,
                attempt_sequence=att.attempt_sequence if att else 1,
                assessment_mode=req.assessment_mode.value if req else "rules",
                exit_code=0 if summary.status == RunStatus.SUCCESS else (4 if summary.status == RunStatus.PARTIAL else 1),
            )
        finally:
            if self._owns_engine:
                engine.close()

    def _execute_pipeline(
        self,
        engine: StorageEngine,
        request: RunRequest,
        attempt: RunAttempt,
        start_time: datetime,
        opts: RunOptions,
        profile: ProfileSnapshot,
        policy: SearchPolicy,
        effective_sources: list[EffectiveSource],
        sync_config: SyncMappingConfig | None,
        app_config: AppConfig | None = None,
        paths: ResolvedPaths | None = None,
    ) -> RunReport:
        """Execute the coordinated stages."""
        run_id = request.run_id
        errors: list[ClassifiedError] = []
        pending_work: list[str] = []
        stage_statuses: dict[str, str] = {}

        # -------------------------------------------------------------
        # Stage 1: Fetch
        # -------------------------------------------------------------
        from job_automation.ingestion.controller import FetchController
        from job_automation.ingestion.ports import AdapterRegistry
        from job_automation.sources.models import SourceRegistryEnvelope
        from job_automation.sources.service import SourceRegistryService

        envelope = SourceRegistryEnvelope(
            schema_version="1.0",
            sources=[s.config for s in effective_sources],
        )
        registry_service = SourceRegistryService.from_envelope(envelope)

        fetch_controller = FetchController(
            storage=engine,
            registry_service=registry_service,
            adapter_registry=AdapterRegistry(),
        )
        fetch_coord = FetchStageCoordinator(engine, fetch_controller)
        engine.runs.record_stage(run_id, "fetch", PipelineStage.RUNNING)
        fetch_res = fetch_coord.execute_fetch(
            request=request,
            attempt=attempt,
        )
        stage_statuses["fetch"] = "succeeded" if fetch_res.sources_failed == 0 else "partial"

        # -------------------------------------------------------------
        # Stage 2: Normalize
        # -------------------------------------------------------------
        from job_automation.ingestion.normalization.service import DefaultNormalizer

        norm_coord = NormalizeStageCoordinator(engine, DefaultNormalizer())
        engine.runs.record_stage(run_id, "normalize", PipelineStage.RUNNING)
        norm_res = norm_coord.execute_normalization(
            request=request,
            attempt=attempt,
            drafts=fetch_res.drafts,
        )
        stage_statuses["normalize"] = "succeeded" if not norm_res.quarantine_records else "partial"

        # -------------------------------------------------------------
        # Stage 3: Identity
        # -------------------------------------------------------------
        id_svc = IdentityService(engine)
        id_coord = IdentityStageCoordinator(engine, id_svc)
        engine.runs.record_stage(run_id, "identity", PipelineStage.RUNNING)
        id_res = id_coord.execute_identity(
            request=request,
            attempt=attempt,
            normalized_postings=norm_res.normalized_postings,
        )
        stage_statuses["identity"] = "succeeded"

        # -------------------------------------------------------------
        # Stage 4: Availability
        # -------------------------------------------------------------
        from job_automation.identity.availability.service import AvailabilityService

        avail_svc = AvailabilityService(engine)
        avail_coord = AvailabilityStageCoordinator(engine, avail_svc)
        engine.runs.record_stage(run_id, "availability", PipelineStage.RUNNING)
        sources_by_key = {s.config.source_key: s for s in effective_sources}
        avail_res = avail_coord.execute_availability(
            request=request,
            attempt=attempt,
            manifests=fetch_res.manifests,
            effective_sources=sources_by_key,
        )
        stage_statuses["availability"] = "succeeded"

        # -------------------------------------------------------------
        # Stage 5: Assessment
        # -------------------------------------------------------------
        asmt_svc = AssessmentService()
        sel_mgr = SelectionManager(engine)
        inval_eval = InvalidationEvaluator(engine)

        llm_assessor = None
        if request.assessment_mode == AssessmentMode.LLM:
            llm_assessor = opts.llm_assessor
            if llm_assessor is None and app_config is not None:
                llm_assessor = build_llm_assessor(
                    engine=engine,
                    config=app_config,
                    transport=opts.model_transport,
                )

        asmt_coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=asmt_svc,
            selection_manager=sel_mgr,
            invalidation_evaluator=inval_eval,
            llm_assessor=llm_assessor,
        )
        engine.runs.record_stage(run_id, "assessment", PipelineStage.RUNNING)

        asmt_res = asmt_coord.execute_assessment(
            request=request,
            attempt=attempt,
            bindings=id_res.bindings,
            profile=profile,
            policy=policy,
            model_identifier=opts.model_identifier,
            prompt_version=opts.prompt_version,
        )
        stage_statuses["assessment"] = "succeeded" if not asmt_res.pending_items else "partial"
        if asmt_res.pending_items:
            pending_work.extend(asmt_res.pending_items)

        # -------------------------------------------------------------
        # Stage 6: Sync
        # -------------------------------------------------------------
        sync_coord = SyncStageCoordinator(engine)
        engine.runs.record_stage(run_id, "sync", PipelineStage.RUNNING)

        sync_res = None
        if opts.enable_sync and sync_config is not None:
            submissions: list[SyncSubmission] = []
            for item in asmt_res.items:
                cjob = engine.canonical_jobs.get_canonical_job(item.selection.canonical_job_id)
                binding = next((b for b in id_res.bindings if b.canonical_job_id == item.selection.canonical_job_id), None)
                if cjob is not None:
                    try:
                        sub = build_sync_submission(
                            selection=item.selection,
                            assessment=item.assessment,
                            canonical_job=cjob,
                            binding=binding,
                            run_id=run_id,
                        )
                        submissions.append(sub)
                    except Exception as exc:
                        errors.append(
                            ClassifiedError(
                                category=ErrorCategory.VALIDATION,
                                message=f"Failed building sync submission for {cjob.canonical_job_id}: {exc}",
                                recoverable=False,
                            )
                        )

            sync_res = sync_coord.execute_sync(
                request=request,
                attempt=attempt,
                submissions=submissions,
                config=sync_config,
                gateway=opts.gateway,
                run_candidate_backup=opts.run_candidate_backup,
            )
            stage_statuses["sync"] = "succeeded" if not sync_res.errors else "partial"
            errors.extend(sync_res.errors)
            if sync_res.pending_operations_count > 0:
                pending_work.append(f"{sync_res.pending_operations_count} pending Salesforce sync operation(s)")
        else:
            stage_statuses["sync"] = "skipped"

        # -------------------------------------------------------------
        # 7. Compile Final C15 RunSummary
        # -------------------------------------------------------------
        end_time = datetime.now(timezone.utc)

        # Source observation counts
        source_counts: dict[str, int] = dict(fetch_res.source_counts)

        # Dispositions
        eligible_count = 0
        review_count = 0
        rejected_count = 0
        for item in asmt_res.items:
            # Only count freshly evaluated items for C15 newly evaluated totals
            if not item.is_reused:
                d = item.assessment.final_disposition.value
                if d == "eligible":
                    eligible_count += 1
                elif d == "review":
                    review_count += 1
                elif d == "rejected":
                    rejected_count += 1

        summary = build_run_summary(
            run_id=run_id,
            start_time=start_time,
            end_time=end_time,
            source_counts=source_counts,
            canonical_jobs_new=id_res.canonical_jobs_new,
            canonical_jobs_updated=id_res.canonical_jobs_updated,
            canonical_jobs_duplicate=id_res.canonical_jobs_duplicate,
            eligible_count=eligible_count,
            review_count=review_count,
            rejected_count=rejected_count,
            sync_operations_succeeded=sync_res.sync_operations_succeeded if sync_res else 0,
            sync_operations_failed=sync_res.sync_operations_failed if sync_res else 0,
            errors=errors,
            pending_work=pending_work,
            is_fatal_failure=False,
            is_partial=(len(errors) > 0 or len(pending_work) > 0),
        )

        engine.runs.complete_run(summary)

        # Update attempt
        exit_code = 0 if summary.status == RunStatus.SUCCESS else (4 if summary.status == RunStatus.PARTIAL else 1)
        att_status = "succeeded" if summary.status == RunStatus.SUCCESS else ("partial" if summary.status == RunStatus.PARTIAL else "failed")
        attempt_update = attempt.model_copy(
            update={
                "status": att_status,
                "completed_at": end_time,
                "exit_code": exit_code,
            }
        )
        engine.pipeline_work.save_run_attempt(attempt_update)

        rep = RunReport(
            c15_summary=summary,
            attempt_sequence=attempt.attempt_sequence,
            assessment_mode=request.assessment_mode.value,
            sources_attempted=[s.config.source_key for s in effective_sources],
            sources_succeeded=[s.config.source_key for s in effective_sources if s.config.source_key in fetch_res.manifests],
            sources_failed=[s.config.source_key for s in effective_sources if s.config.source_key not in fetch_res.manifests],
            quarantined_records_count=len(norm_res.quarantine_records),
            availability_transitions_count=len(avail_res.changed_canonical_ids),
            reused_assessments_count=asmt_res.reused_count,
            model_invocations_count=asmt_res.model_invocations_count,
            candidate_backup_records_read=sync_res.backup_result.records_read if sync_res and sync_res.backup_result else 0,
            candidate_backup_snapshots_saved=sync_res.backup_result.snapshots_saved if sync_res and sync_res.backup_result else 0,
            candidate_backup_complete=sync_res.backup_result.is_complete if sync_res and sync_res.backup_result else True,
            stage_statuses=stage_statuses,
            exit_code=exit_code,
        )
        return self._finalize_and_record_summary(engine, paths, opts, rep)
