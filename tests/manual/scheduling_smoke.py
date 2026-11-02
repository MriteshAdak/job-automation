"""Manual smoke verification script for AUTO-01 native Windows scheduling and startup.

Validates end-to-end scheduling and startup integration on native Windows:
1. Provisions isolated synthetic data root with Windows path spaces and umlauts:
   'Zeitplan Prüfung / Scheduling 2026'
2. Verifies storage migrations (Migration 016) and scheduling schema creation.
3. Validates calendar calculations:
   - Europe/Berlin civil time mapping.
   - Spring gap shift (2027-03-28 02:30 -> 03:00 CEST / 01:00 UTC).
   - Autumn fold disambiguation (2027-10-31 02:30 -> fold 0, 00:30 UTC).
   - Coalescing multiple missed runs within 24h into a single eligible slot.
   - Expiring missed runs older than 24h.
4. Probes model service readiness on loopback.
5. Generates non-secret identity and path resource manifest.
6. Exports reviewable Windows Task Scheduler XML definitions and validates XML structure.
7. Tests mutual exclusion:
   - Manual worker holds WindowsWorkerLock.
   - Dispatcher detects contention and exits code 3 (SKIPPED_BUSY).
8. Cleans up synthetic test directories.

Usage:
    .venv\\Scripts\\python.exe tests/manual/scheduling_smoke.py
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_automation.cli import main
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.operations.records import OperationsSettings
from job_automation.operations.scheduling.calendar import CalendarCalculator
from job_automation.operations.scheduling.dispatcher import SchedulingDispatcher
from job_automation.operations.scheduling.readiness import probe_model_readiness
from job_automation.operations.scheduling.records import (
    OccurrenceOutcome,
    ScheduleDefinition,
    ScheduleKind,
)
from job_automation.operations.scheduling.service import SchedulingService
from job_automation.storage.engine import StorageEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scheduling_smoke")


def run_smoke() -> int:
    temp_dir = Path(tempfile.mkdtemp(prefix="auto01_smoke_"))
    try:
        data_root = temp_dir / "Zeitplan Prüfung" / "Scheduling 2026"
        data_root.mkdir(parents=True, exist_ok=True)
        config_path = temp_dir / "config.json"
        ops_config_path = temp_dir / "operations.json"

        ops_settings = OperationsSettings()
        ops_config_path.write_text(ops_settings.model_dump_json(indent=2), encoding="utf-8")

        app_config_data = {
            "app_name": "JobAutomationSmoke",
            "schema_version": "1.0",
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://127.0.0.1:11434",
            "operations_settings_ref": str(ops_config_path),
        }
        config_path.write_text(json.dumps(app_config_data, indent=2), encoding="utf-8")

        logger.info("1. Initializing StorageEngine and applying Migration 016...")
        engine = StorageEngine(
            db_path=data_root / "database" / "job_automation.db",
            raw_dir=data_root / "raw",
            artifacts_dir=data_root / "artifacts",
        )
        engine.migrate()

        # Verify tables created
        cur = engine.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ops_schedule%'")
        tables = [r[0] for r in cur.fetchall()]
        assert "ops_schedule_definitions" in tables, "ops_schedule_definitions missing"
        assert "ops_schedule_occurrences" in tables, "ops_schedule_occurrences missing"
        cur = engine.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = 'ops_launch_attempts'")
        assert len(cur.fetchall()) == 1, "ops_launch_attempts missing"
        engine.close()
        logger.info("   Migration 016 verified successfully.")

        logger.info("2. Testing CalendarCalculator DST anomalies & coalescing...")
        calc = CalendarCalculator("Europe/Berlin")

        # Spring gap
        spring_slot = calc.resolve_slot(date(2027, 3, 28), "02:30")
        assert spring_slot.is_gap_adjusted is True
        assert spring_slot.intended_slot_key == "2027-03-28T02:30:00 Europe/Berlin"
        assert spring_slot.intended_utc_instant == datetime(2027, 3, 28, 1, 0, tzinfo=timezone.utc)
        logger.info("   Spring forward gap: 02:30 correctly mapped to 03:00 CEST (01:00 UTC).")

        # Autumn fold
        fall_slot = calc.resolve_slot(date(2027, 10, 31), "02:30")
        assert fall_slot.fold == 0
        assert fall_slot.intended_utc_instant == datetime(2027, 10, 31, 0, 30, tzinfo=timezone.utc)
        logger.info("   Autumn fold: 02:30 evaluated at first occurrence (fold=0, 00:30 UTC).")

        # Coalescing
        dep_id = "dep_smoke"
        definition = ScheduleDefinition(
            deployment_id=dep_id,
            schedule_id="default_search",
            version=1,
            enabled=True,
            work_kind=ScheduleKind.SEARCH,
            timezone="Europe/Berlin",
            target_times=["07:00", "19:00"],
            activation_epoch=datetime(2026, 10, 28, 0, 0, tzinfo=timezone.utc),
            max_lateness_hours=24,
            app_config_path=str(config_path),
            data_root=str(data_root),
            assessment_mode="rules",
            llm_strategy="json",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        as_of = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
        due, non_due = calc.evaluate_due_occurrences(definition, [], as_of)
        assert due is not None
        assert due.intended_slot == "2026-10-31T07:00:00 Europe/Berlin"
        # Older missed runs coalesced / expired
        outcomes = {o.intended_slot: o.outcome for o in non_due}
        assert outcomes["2026-10-30T19:00:00 Europe/Berlin"] == OccurrenceOutcome.COALESCED
        assert outcomes["2026-10-30T07:00:00 Europe/Berlin"] == OccurrenceOutcome.EXPIRED
        logger.info("   Coalescing: 2026-10-30 19:00 coalesced, 2026-10-30 07:00 expired (>24h), 2026-10-31 07:00 admitted as due.")

        logger.info("3. Testing Model Supervisor readiness probe...")
        probe = probe_model_readiness("http://127.0.0.1:11434", timeout_seconds=1.0)
        logger.info("   Loopback Ollama probe: is_ready=%s, category=%s, details=%s", probe.is_ready, probe.category.value, probe.details)

        logger.info("4. Testing Manifest generation...")
        service = SchedulingService(config_path=config_path, data_root=data_root)
        manifest = service.generate_manifest()
        assert manifest.account_name == getpass.getuser()
        assert manifest.logon_type == "Password"
        assert manifest.is_batch_logon_verified is False
        assert str(data_root) in manifest.acl_matrix
        logger.info("   Manifest verified (account=%s, logon_type=%s, secret-free).", manifest.account_name, manifest.logon_type)

        logger.info("5. Testing Task Scheduler XML export...")
        task_out = temp_dir / "tasks"
        paths_dict = service.export_task_definitions(task_out)
        disp_xml_file = Path(paths_dict["dispatcher_xml"])
        assert disp_xml_file.is_file()

        # Parse XML
        xml_content = disp_xml_file.read_text(encoding="utf-16")
        root = ET.fromstring(xml_content)
        assert "Task" in root.tag
        settings_elem = root.find("{http://schemas.microsoft.com/windows/2004/02/mit/task}Settings")
        assert settings_elem is not None
        mult_elem = settings_elem.find("{http://schemas.microsoft.com/windows/2004/02/mit/task}MultipleInstancesPolicy")
        assert mult_elem is not None and mult_elem.text == "IgnoreNew"
        en_elem = settings_elem.find("{http://schemas.microsoft.com/windows/2004/02/mit/task}Enabled")
        assert en_elem is not None and en_elem.text == "false"
        logger.info("   XML verified: Task Scheduler 2.0 schema, MultipleInstancesPolicy=IgnoreNew, Enabled=false.")

        logger.info("6. Testing Lock Contention (Manual vs Scheduled)...")
        # Hold manual worker lock
        worker_lock = WindowsWorkerLock(data_root)
        with worker_lock.acquire(owner_kind=OwnerKind.SEARCH):
            # Seed definition with earlier activation epoch
            service.set_enabled(True)
            engine = StorageEngine(
                db_path=data_root / "database" / "job_automation.db",
                raw_dir=data_root / "raw",
                artifacts_dir=data_root / "artifacts",
            )
            _, paths, app_config = service._get_engine_and_paths()
            def_active = service.dispatcher.get_or_create_default_definition(engine, paths, app_config)
            def_active = def_active.model_copy(update={"enabled": True, "activation_epoch": datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)})
            engine.scheduling.save_definition(def_active)
            engine.close()

            # Dispatcher must detect lock contention and exit code 3
            rc = main([
                "ops", "schedule", "dispatch",
                "--config", str(config_path),
                "--data-root", str(data_root),
                "--as-of", "2026-10-31T10:00:00+00:00",
                "--json",
            ])
            assert rc == 3, f"Expected exit code 3 on lock contention, got {rc}"
            logger.info("   Lock contention verified: dispatcher child returned exit code 3.")

        logger.info("AUTO-01 Manual Smoke Verification PASSED successfully!")
        return 0

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_smoke())
