"""Native Windows restart and crash recovery tests across processes (RUN-01-S02, S03, S10)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability, RunStatus
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.orchestration.records import PostingBinding, RunAttempt, RunRequest
from job_automation.orchestration.recovery import RecoveryManager
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine


class TestWindowsRestart:
    def test_killed_worker_allows_subsequent_process_recovery(self, tmp_path: Path) -> None:
        """When a worker process holding the lock is killed, lock is freed and run resumes cleanly."""
        data_root = tmp_path / "CrashRecoveryStore ö"
        data_root.mkdir(parents=True, exist_ok=True)
        ready_file = tmp_path / "worker_ready.txt"
        worker_script = Path(__file__).resolve().parent.parent / "fakes" / "lock_worker.py"

        # 1. Initialize DB with an interrupted run attempt
        db_path = data_root / "job_automation.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        engine.runs.create_run(run_id=run_id, start_time=now, status="running")
        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
        att1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_request(req)
        engine.pipeline_work.save_run_attempt(att1)

        # 2. Spawn a subprocess holding the deployment lock
        proc = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "--data-root",
                str(data_root),
                "--owner-kind",
                "search",
                "--hold-seconds",
                "10.0",
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Wait for subprocess to hold the lock
            child_pid = None
            for _ in range(50):
                if ready_file.is_file() and ready_file.stat().st_size > 0:
                    try:
                        child_pid = int(ready_file.read_text(encoding="utf-8").strip())
                        break
                    except ValueError:
                        pass
                    time.sleep(0.05)
                time.sleep(0.05)
            assert child_pid is not None, "Child worker failed to signal readiness"

            # 3. Simulate sudden ungraceful crash (kill process)
            proc.kill()
            proc.wait(timeout=3.0)

            # 4. OS immediately frees file lock; another process acquires immediately
            lock = WindowsWorkerLock(data_root)
            token = lock.acquire_lock()
            assert token is not None
            assert token.is_released is False
            token.release()

            # 5. RecoveryManager reconciles interrupted attempt
            rec_mgr = RecoveryManager(engine)
            rec_plan = rec_mgr.reconcile_interrupted_run(run_id)

            assert rec_plan.next_attempt_sequence == 2
            assert rec_plan.prior_attempt is not None
            assert rec_plan.prior_attempt.attempt_sequence == 1

            # Previous attempt status updated to interrupted/failed
            latest_att = engine.pipeline_work.get_latest_attempt(run_id)
            assert latest_att is not None
            assert latest_att.status == "interrupted"

            # 6. PipelineRunner resume_run executes new attempt and finishes cleanly
            cand_id = uuid.uuid4()
            profile = ProfileSnapshot(
                candidate_id=cand_id,
                profile_version="v1",
                approval_metadata=ProfileApprovalMetadata(
                    is_approved=True,
                    approved_by="Candidate",
                    approved_at=now,
                ),
                explicit_eligibility=CandidateEligibility(
                    work_authorization_countries=["DE"],
                    remote_eligible=True,
                ),
                evidence_records=[],
            )
            policy = SearchPolicy(
                policy_version="v1",
                hard_criteria=[],
                preferences=[],
                exclusions=[],
            )

            runner = PipelineRunner(data_root=data_root, engine=engine)
            opts = RunOptions(
                assessment_mode="rules",
                enable_sync=False,
            )
            report = runner.resume_run(
                run_id=run_id,
                options=opts,
                profile_override=profile,
                policy_override=policy,
                effective_sources_override=[],
            )

            assert report.exit_code == 0
            assert report.attempt_sequence == 2
            assert report.c15_summary.status == RunStatus.SUCCESS

        finally:
            if proc.poll() is None:
                proc.kill()
            engine.close()
