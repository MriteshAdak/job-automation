"""Scheduling dispatcher executing due occurrences via native CLI subprocesses (AUTO-01-S03, S04, S05, S06).

Enforces:
- Bounded execution of due Europe/Berlin slots.
- Re-use and recovery of admitted unfinished runs via 'run resume'.
- Mutual exclusion with manual workers and maintenance through existing WindowsWorkerLock.
- Contention handling: exit code 3 cleanly records SKIPPED_BUSY with deferred retry.
- Model supervisor readiness check prior to LLM admission (bypassed for rules mode).
- Durable companion receipts in ops_schedule_occurrences and ops_launch_attempts.
- Sanitized diagnostic logging without credentials or private data.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from job_automation.configuration import AppConfig, ResolvedPaths, load_config
from job_automation.operations.scheduling.calendar import CalendarCalculator
from job_automation.operations.scheduling.launcher import LaunchResult, SubprocessLauncher
from job_automation.operations.scheduling.readiness import probe_model_readiness
from job_automation.operations.scheduling.records import (
    BootstrapCategory,
    DispatchReport,
    LaunchAttemptRecord,
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleOccurrence,
)
if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def derive_default_deployment_id(data_root: str | Path) -> str:
    """Generate a stable deployment ID from hostname, user, and normalized data path."""
    import hashlib
    norm = str(Path(data_root).resolve()).lower()
    user = getpass.getuser()
    raw = f"{user}@{norm}"
    return f"dep_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:12]}"


class SchedulingDispatcher:
    """Evaluates and dispatches scheduled work items for a deployment."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        data_root: str | Path | None = None,
        python_executable: str | Path | None = None,
        working_dir: str | Path | None = None,
    ) -> None:
        self.config_path = str(config_path) if config_path else None
        self.data_root = str(data_root) if data_root else None
        self.launcher = SubprocessLauncher(
            python_executable=python_executable,
            working_dir=working_dir,
        )

    def _get_engine_and_paths(self) -> tuple[StorageEngine, ResolvedPaths, AppConfig]:
        from job_automation.storage.engine import StorageEngine

        config, paths = load_config(
            config_path=self.config_path,
            data_root_override=self.data_root,
        )
        engine = StorageEngine.from_config(config, paths)
        engine.migrate()
        return engine, paths, config

    def get_or_create_default_definition(
        self,
        engine: StorageEngine,
        paths: ResolvedPaths,
        app_config: AppConfig,
        work_kind: ScheduleKind = ScheduleKind.SEARCH,
    ) -> ScheduleDefinition:
        """Fetch active definition or initialize disabled default definition."""
        dep_id = derive_default_deployment_id(paths.data_root)
        schedule_id = f"default_{work_kind.value}"
        existing = engine.scheduling.get_definition(dep_id, schedule_id)
        if existing is not None:
            return existing

        now_utc = datetime.now(timezone.utc)
        default_def = ScheduleDefinition(
            deployment_id=dep_id,
            schedule_id=schedule_id,
            version=1,
            enabled=False,  # Disabled by default
            work_kind=work_kind,
            timezone=app_config.display_timezone,
            target_times=["07:00"],
            activation_epoch=now_utc,
            max_lateness_hours=24,
            max_retries=3,
            retry_delay_seconds=60,
            app_config_path=str(self.config_path or ""),
            data_root=str(paths.data_root),
            assessment_mode="rules",
            llm_strategy="json",
            created_at=now_utc,
            updated_at=now_utc,
        )
        engine.scheduling.save_definition(default_def)
        return default_def

    def dispatch(
        self,
        as_of_utc: datetime | None = None,
        force_run: bool = False,
        work_kind: ScheduleKind = ScheduleKind.SEARCH,
    ) -> DispatchReport:
        """Evaluate schedule, recover interrupted work, or admit and launch due slots."""
        as_of = as_of_utc or datetime.now(timezone.utc)
        engine, paths, app_config = self._get_engine_and_paths()

        try:
            definition = self.get_or_create_default_definition(
                engine=engine,
                paths=paths,
                app_config=app_config,
                work_kind=work_kind,
            )

            # 1. Master toggle check
            if not definition.enabled and not force_run:
                return DispatchReport(
                    status="disabled",
                    exit_code=0,
                    message=f"Schedule '{definition.schedule_id}' is disabled. No work dispatched.",
                    details={"deployment_id": definition.deployment_id, "schedule_id": definition.schedule_id},
                )

            identity_name = getpass.getuser()

            # 2. Check for unfinished admitted occurrence needing recovery
            due_or_retryable = engine.scheduling.get_due_or_retryable_occurrences(
                deployment_id=definition.deployment_id,
                as_of_utc=as_of,
            )

            unfinished_with_run = next(
                (o for o in due_or_retryable if o.admitted_run_id and o.outcome in (OccurrenceOutcome.IN_PROGRESS, OccurrenceOutcome.PARTIAL)),
                None,
            )

            if unfinished_with_run is not None:
                # Resume unfinished admitted run
                logger.info("Resuming unfinished occurrence '%s' with run ID '%s'", unfinished_with_run.occurrence_id, unfinished_with_run.admitted_run_id)
                args = [
                    "-m", "job_automation", "run", "resume",
                    "--run-id", str(unfinished_with_run.admitted_run_id),
                    "--json",
                ]
                if self.config_path:
                    args.extend(["--config", self.config_path])
                if self.data_root:
                    args.extend(["--data-root", self.data_root])

                start_launch = datetime.now(timezone.utc)
                res = self.launcher.launch(args, timeout_seconds=definition.command_timeout_seconds)
                comp_launch = datetime.now(timezone.utc)

                # Record launch attempt
                attempt = LaunchAttemptRecord(
                    occurrence_id=unfinished_with_run.occurrence_id,
                    deployment_id=definition.deployment_id,
                    schedule_id=definition.schedule_id,
                    work_kind=definition.work_kind,
                    task_identity=identity_name,
                    started_at=start_launch,
                    completed_at=comp_launch,
                    bootstrap_status=BootstrapCategory.OK,
                    child_pid=res.pid,
                    child_exit_code=res.exit_code,
                    outcome=res.outcome,
                    application_run_id=unfinished_with_run.admitted_run_id,
                    report_summary_json=res.json_payload,
                    sanitized_error=res.stderr[:2048] if res.stderr else None,
                    stdout_tail=res.stdout,
                    stderr_tail=res.stderr,
                )
                engine.scheduling.save_launch_attempt(attempt)

                # Update occurrence
                now_utc = datetime.now(timezone.utc)
                if res.exit_code == 0:
                    unfinished_with_run = unfinished_with_run.model_copy(
                        update={
                            "outcome": OccurrenceOutcome.SUCCEEDED,
                            "terminal_at": now_utc,
                            "updated_at": now_utc,
                        }
                    )
                elif res.exit_code == 3:
                    unfinished_with_run = unfinished_with_run.model_copy(
                        update={
                            "outcome": OccurrenceOutcome.SKIPPED_BUSY,
                            "next_eligible_at": now_utc + timedelta(seconds=definition.retry_delay_seconds),
                            "updated_at": now_utc,
                        }
                    )
                elif res.exit_code == 4:
                    unfinished_with_run = unfinished_with_run.model_copy(
                        update={
                            "outcome": OccurrenceOutcome.PARTIAL,
                            "next_eligible_at": now_utc + timedelta(seconds=definition.retry_delay_seconds),
                            "updated_at": now_utc,
                        }
                    )
                else:
                    unfinished_with_run = unfinished_with_run.model_copy(
                        update={
                            "outcome": OccurrenceOutcome.FAILED,
                            "retry_count": unfinished_with_run.retry_count + 1,
                            "terminal_at": now_utc if unfinished_with_run.retry_count + 1 >= definition.max_retries else None,
                            "next_eligible_at": now_utc + timedelta(seconds=definition.retry_delay_seconds * 2) if unfinished_with_run.retry_count + 1 < definition.max_retries else None,
                            "updated_at": now_utc,
                        }
                    )
                engine.scheduling.save_occurrence(unfinished_with_run)

                return DispatchReport(
                    status="resumed",
                    exit_code=res.exit_code,
                    message=f"Resumed previous unfinished run '{unfinished_with_run.admitted_run_id}' with exit code {res.exit_code}.",
                    occurrence_id=unfinished_with_run.occurrence_id,
                    run_id=unfinished_with_run.admitted_run_id,
                    launch_id=attempt.launch_id,
                )

            # 3. Check for existing retryable occurrence, or perform calendar evaluation
            due_occ = next(
                (o for o in due_or_retryable if o.outcome in (OccurrenceOutcome.DUE, OccurrenceOutcome.FAILED, OccurrenceOutcome.SKIPPED_BUSY)),
                None,
            )

            if due_occ is None:
                calc = CalendarCalculator(definition.timezone)
                existing_occs = engine.scheduling.list_occurrences(
                    deployment_id=definition.deployment_id,
                    schedule_id=definition.schedule_id,
                    limit=200,
                )

                due_occ, non_due_occs = calc.evaluate_due_occurrences(
                    definition=definition,
                    existing_occurrences=existing_occs,
                    as_of_utc=as_of,
                )

                # Persist newly recorded expired / coalesced records
                for nd in non_due_occs:
                    engine.scheduling.save_occurrence(nd)

                if due_occ is None:
                    # Perform light preflight health probe if configured
                    return DispatchReport(
                        status="idle",
                        exit_code=0,
                        message="No due slots found as of current timestamp.",
                        details={"as_of": as_of.isoformat(), "coalesced_or_expired_count": len(non_due_occs)},
                    )

            # 4. Save due occurrence
            engine.scheduling.save_occurrence(due_occ)

            # 5. Model readiness probe if LLM assessment mode is active
            if definition.assessment_mode == "llm":
                model_probe = probe_model_readiness(
                    url=app_config.model_service_url,
                    required_model=app_config.model_provider.model_identifier if app_config.model_provider else None,
                    timeout_seconds=3.0,
                )
                if not model_probe.is_ready:
                    now_utc = datetime.now(timezone.utc)
                    attempt = LaunchAttemptRecord(
                        occurrence_id=due_occ.occurrence_id,
                        deployment_id=definition.deployment_id,
                        schedule_id=definition.schedule_id,
                        work_kind=definition.work_kind,
                        task_identity=identity_name,
                        started_at=now_utc,
                        completed_at=now_utc,
                        bootstrap_status=model_probe.category,
                        readiness_message=model_probe.details,
                        outcome="bootstrap_failed",
                        sanitized_error=model_probe.details,
                    )
                    engine.scheduling.save_launch_attempt(attempt)

                    due_occ = due_occ.model_copy(
                        update={
                            "outcome": OccurrenceOutcome.FAILED,
                            "retry_count": due_occ.retry_count + 1,
                            "next_eligible_at": now_utc + timedelta(seconds=definition.retry_delay_seconds),
                            "updated_at": now_utc,
                        }
                    )
                    engine.scheduling.save_occurrence(due_occ)

                    return DispatchReport(
                        status="model_offline",
                        exit_code=2,
                        message=f"Model readiness check failed: {model_probe.details}",
                        occurrence_id=due_occ.occurrence_id,
                        launch_id=attempt.launch_id,
                    )

            # 6. Mark occurrence IN_PROGRESS and launch CLI command
            now_utc = datetime.now(timezone.utc)
            due_occ = due_occ.model_copy(
                update={
                    "outcome": OccurrenceOutcome.IN_PROGRESS,
                    "updated_at": now_utc,
                }
            )
            engine.scheduling.save_occurrence(due_occ)

            # Build command arguments
            cmd_args = [
                "-m", "job_automation", "run", "start",
                "--assessment-mode", definition.assessment_mode,
                "--llm-strategy", definition.llm_strategy,
                "--trigger-kind", "scheduled",
                "--schedule-occurrence-id", str(due_occ.occurrence_id),
                "--slot-key", due_occ.intended_slot,
                "--json",
            ]
            if self.config_path:
                cmd_args.extend(["--config", self.config_path])
            if self.data_root:
                cmd_args.extend(["--data-root", self.data_root])
            if definition.run_config_path:
                cmd_args.extend(["--run-config", definition.run_config_path])

            start_launch = datetime.now(timezone.utc)
            res = self.launcher.launch(cmd_args, timeout_seconds=definition.command_timeout_seconds)
            comp_launch = datetime.now(timezone.utc)

            # Record launch attempt audit
            attempt = LaunchAttemptRecord(
                occurrence_id=due_occ.occurrence_id,
                deployment_id=definition.deployment_id,
                schedule_id=definition.schedule_id,
                work_kind=definition.work_kind,
                task_identity=identity_name,
                started_at=start_launch,
                completed_at=comp_launch,
                bootstrap_status=BootstrapCategory.OK,
                child_pid=res.pid,
                child_exit_code=res.exit_code,
                outcome=res.outcome,
                application_run_id=res.run_id,
                report_summary_json=res.json_payload,
                sanitized_error=res.stderr[:2048] if res.stderr else None,
                stdout_tail=res.stdout,
                stderr_tail=res.stderr,
            )
            engine.scheduling.save_launch_attempt(attempt)

            # Update occurrence final state
            fin_utc = datetime.now(timezone.utc)
            if res.exit_code == 0:
                due_occ = due_occ.model_copy(
                    update={
                        "outcome": OccurrenceOutcome.SUCCEEDED,
                        "admitted_run_id": res.run_id,
                        "terminal_at": fin_utc,
                        "updated_at": fin_utc,
                    }
                )
            elif res.exit_code == 3:
                # Contention: Lock held by manual worker or maintenance
                due_occ = due_occ.model_copy(
                    update={
                        "outcome": OccurrenceOutcome.SKIPPED_BUSY,
                        "next_eligible_at": fin_utc + timedelta(seconds=definition.retry_delay_seconds),
                        "updated_at": fin_utc,
                    }
                )
            elif res.exit_code == 4:
                # Partial success (some sources failed or quarantine items)
                due_occ = due_occ.model_copy(
                    update={
                        "outcome": OccurrenceOutcome.PARTIAL,
                        "admitted_run_id": res.run_id,
                        "next_eligible_at": fin_utc + timedelta(seconds=definition.retry_delay_seconds),
                        "updated_at": fin_utc,
                    }
                )
            else:
                new_retries = due_occ.retry_count + 1
                is_terminal = new_retries >= definition.max_retries
                due_occ = due_occ.model_copy(
                    update={
                        "outcome": OccurrenceOutcome.FAILED,
                        "admitted_run_id": res.run_id,
                        "retry_count": new_retries,
                        "terminal_at": fin_utc if is_terminal else None,
                        "next_eligible_at": fin_utc + timedelta(seconds=definition.retry_delay_seconds * (2 ** (new_retries - 1))) if not is_terminal else None,
                        "updated_at": fin_utc,
                    }
                )
            engine.scheduling.save_occurrence(due_occ)

            return DispatchReport(
                status=res.outcome,
                exit_code=res.exit_code,
                message=f"Dispatched slot '{due_occ.intended_slot}' with outcome '{res.outcome}' (exit code {res.exit_code}).",
                occurrence_id=due_occ.occurrence_id,
                run_id=res.run_id,
                launch_id=attempt.launch_id,
                details={"exit_code": res.exit_code, "duration_s": res.duration_seconds},
            )

        finally:
            engine.close()
