"""High-level management service for native Windows startup and scheduling (AUTO-01).

Provides operations for:
- Status inspection (definition, next slot, last launch result, occurrences).
- Dry-run schedule evaluation (slot calculation, gap/fold, coalescing).
- Live dispatch execution.
- Reviewable task XML export and inspectable setup.
- Non-secret execution identity and path manifest generation.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from job_automation.configuration import AppConfig, ResolvedPaths, load_config
from job_automation.operations.scheduling.calendar import CalendarCalculator
from job_automation.operations.scheduling.dispatcher import (
    SchedulingDispatcher,
    derive_default_deployment_id,
)
from job_automation.operations.scheduling.readiness import probe_model_readiness
from job_automation.operations.scheduling.records import (
    DispatchReport,
    IdentityResourceManifest,
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleKind,
)
from job_automation.operations.scheduling.task_xml import (
    generate_dispatcher_task_xml,
    generate_model_supervisor_task_xml,
)
if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class SchedulingService:
    """Service facade coordinating scheduling operations, inspection, and task definitions."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        data_root: str | Path | None = None,
    ) -> None:
        self.config_path = str(config_path) if config_path else None
        self.data_root = str(data_root) if data_root else None
        self.dispatcher = SchedulingDispatcher(
            config_path=self.config_path,
            data_root=self.data_root,
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

    def inspect_status(self) -> dict[str, Any]:
        """Inspect current scheduling status, definitions, next due slot, and last launch."""
        engine, paths, config = self._get_engine_and_paths()
        try:
            dep_id = derive_default_deployment_id(paths.data_root)
            definitions = engine.scheduling.list_definitions(dep_id)
            if not definitions:
                def_obj = self.dispatcher.get_or_create_default_definition(engine, paths, config)
                definitions = [def_obj]
            else:
                def_obj = definitions[0]

            latest_launch = engine.scheduling.get_latest_launch_attempt(dep_id)
            occurrences = engine.scheduling.list_occurrences(deployment_id=dep_id, limit=20)

            # Compute next due slot
            now_utc = datetime.now(timezone.utc)
            calc = CalendarCalculator(def_obj.timezone)
            future_slots = calc.generate_slots_in_range(def_obj, now_utc, now_utc + timedelta(days=2))

            # Check model readiness probe
            model_probe = probe_model_readiness(
                url=config.model_service_url,
                required_model=config.model_provider.model_identifier if config.model_provider else None,
                timeout_seconds=1.0,
            )

            status_dict = {
                "deployment_id": dep_id,
                "data_root": str(paths.data_root),
                "timezone": def_obj.timezone,
                "enabled": def_obj.enabled,
                "next_slot": future_slots[0].intended_slot_key if future_slots else None,
                "work_kind": def_obj.work_kind.value,
                "target_times": def_obj.target_times,
                "assessment_mode": def_obj.assessment_mode,
                "llm_strategy": def_obj.llm_strategy,
                "model_service_url": config.model_service_url,
                "model_status": {
                    "is_ready": model_probe.is_ready,
                    "category": model_probe.category.value,
                    "details": model_probe.details,
                    "installed_models": model_probe.installed_models,
                },
                "last_launch": {
                    "launch_id": str(latest_launch.launch_id) if latest_launch else None,
                    "started_at": latest_launch.started_at.isoformat() if latest_launch else None,
                    "outcome": latest_launch.outcome if latest_launch else None,
                    "exit_code": latest_launch.child_exit_code if latest_launch else None,
                    "application_run_id": str(latest_launch.application_run_id) if latest_launch and latest_launch.application_run_id else None,
                } if latest_launch else None,
                "recent_occurrences_count": len(occurrences),
                "recent_occurrences": [
                    {
                        "occurrence_id": str(o.occurrence_id),
                        "slot": o.intended_slot,
                        "outcome": o.outcome.value,
                        "admitted_run_id": str(o.admitted_run_id) if o.admitted_run_id else None,
                        "retry_count": o.retry_count,
                    }
                    for o in occurrences[:5]
                ],
            }
            return status_dict
        finally:
            engine.close()

    def evaluate_preview(self, as_of_utc: datetime | None = None) -> dict[str, Any]:
        """Dry-run evaluation of due, coalesced, or expired slots without executing."""
        as_of = as_of_utc or datetime.now(timezone.utc)
        engine, paths, config = self._get_engine_and_paths()
        try:
            dep_id = derive_default_deployment_id(paths.data_root)
            def_obj = self.dispatcher.get_or_create_default_definition(engine, paths, config)

            calc = CalendarCalculator(def_obj.timezone)
            existing = engine.scheduling.list_occurrences(dep_id, def_obj.schedule_id, limit=200)

            due_occ, non_due = calc.evaluate_due_occurrences(def_obj, existing, as_of)

            return {
                "deployment_id": dep_id,
                "as_of_utc": as_of.isoformat(),
                "enabled": def_obj.enabled,
                "due_occurrence": {
                    "occurrence_id": str(due_occ.occurrence_id),
                    "intended_slot": due_occ.intended_slot,
                    "utc_instant": due_occ.intended_utc_instant.isoformat(),
                    "offset_minutes": due_occ.local_offset_minutes,
                    "fold": due_occ.fold,
                } if due_occ else None,
                "coalesced_or_expired": [
                    {
                        "occurrence_id": str(o.occurrence_id),
                        "intended_slot": o.intended_slot,
                        "outcome": o.outcome.value,
                    }
                    for o in non_due
                ],
            }
        finally:
            engine.close()

    def dispatch_work(self, as_of_utc: datetime | None = None, force: bool = False) -> DispatchReport:
        """Execute dispatcher."""
        return self.dispatcher.dispatch(as_of_utc=as_of_utc, force_run=force)

    def generate_manifest(self) -> IdentityResourceManifest:
        """Produce non-secret execution identity and path resource manifest."""
        engine, paths, config = self._get_engine_and_paths()
        try:
            user = getpass.getuser()
            py_exe = str(Path(sys.executable).resolve())
            repo_root = str(Path(__file__).resolve().parent.parent.parent.parent.parent)

            # Detect ollama executable on system PATH if available
            ollama_path = shutil.which("ollama") or shutil.which("ollama.exe")
            if not ollama_path:
                local_app = os.environ.get("LOCALAPPDATA")
                if local_app:
                    cand = Path(local_app) / "Programs" / "Ollama" / "ollama.exe"
                    if cand.is_file():
                        ollama_path = str(cand)

            acl_matrix = {
                str(paths.data_root): "Read/Write/Delete (SQLite, WAL, indexes, artifacts, logs)",
                str(paths.database_path.parent): "Read/Write (Database container)",
                str(paths.data_root / ".deployment.lock"): "Exclusive byte locking (Read/Write)",
                py_exe: "Read/Execute (Python runtime)",
                repo_root: "Read/Execute (Application code)",
            }

            return IdentityResourceManifest(
                account_name=user,
                logon_type="Password",
                python_executable=py_exe,
                package_root=repo_root,
                data_root=str(paths.data_root),
                app_config_path=str(self.config_path or ""),
                model_service_url=config.model_service_url,
                model_binary_path=ollama_path,
                model_name=config.model_provider.model_identifier if config.model_provider else None,
                is_batch_logon_verified=False,
                acl_matrix=acl_matrix,
            )
        finally:
            engine.close()

    def export_task_definitions(self, output_dir: Path | str) -> dict[str, str]:
        """Generate reviewable Windows Task XML definitions to output directory."""
        engine, paths, config = self._get_engine_and_paths()
        try:
            def_obj = self.dispatcher.get_or_create_default_definition(engine, paths, config)
            out_path = Path(output_dir).resolve()
            out_path.mkdir(parents=True, exist_ok=True)

            py_exe = Path(sys.executable).resolve()
            repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent

            # 1. Dispatcher Task XML
            dispatcher_xml = generate_dispatcher_task_xml(
                definition=def_obj,
                python_exe=py_exe,
                repo_or_package_dir=repo_root,
                task_name="JobAutomation_Dispatcher",
            )
            disp_file = out_path / "JobAutomation_Dispatcher.xml"
            disp_file.write_text(dispatcher_xml, encoding="utf-16")

            # 2. Model Supervisor Task XML
            ollama_path = shutil.which("ollama") or shutil.which("ollama.exe") or "ollama.exe"
            model_xml = generate_model_supervisor_task_xml(
                ollama_exe=ollama_path,
                task_name="JobAutomation_ModelSupervisor",
            )
            model_file = out_path / "JobAutomation_ModelSupervisor.xml"
            model_file.write_text(model_xml, encoding="utf-16")

            return {
                "dispatcher_xml": str(disp_file),
                "model_supervisor_xml": str(model_file),
            }
        finally:
            engine.close()

    def set_enabled(self, enabled: bool) -> ScheduleDefinition:
        """Enable or disable scheduling for this deployment."""
        engine, paths, config = self._get_engine_and_paths()
        try:
            dep_id = derive_default_deployment_id(paths.data_root)
            def_obj = self.dispatcher.get_or_create_default_definition(engine, paths, config)
            now_utc = datetime.now(timezone.utc)
            updated = def_obj.model_copy(
                update={
                    "enabled": enabled,
                    "updated_at": now_utc,
                }
            )
            engine.scheduling.save_definition(updated)
            return updated
        finally:
            engine.close()
