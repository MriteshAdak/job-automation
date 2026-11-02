"""Tests for cross-process native Windows process ownership and killed worker recovery (RUN-01-S02)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock


class TestWindowsLockProcesses:
    def test_two_native_python_processes_contend(self, tmp_path: Path) -> None:
        data_root = tmp_path / "MultiProcessStore ä"
        ready_file = tmp_path / "worker_ready.txt"
        worker_script = Path(__file__).resolve().parent.parent / "fakes" / "lock_worker.py"

        # Start child process that holds the lock for 3 seconds
        proc = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "--data-root",
                str(data_root),
                "--owner-kind",
                "search",
                "--hold-seconds",
                "3.0",
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Wait for child worker to acquire lock
            child_pid = None
            for _ in range(50):
                if ready_file.is_file() and ready_file.stat().st_size > 0:
                    try:
                        child_pid = int(ready_file.read_text(encoding="utf-8").strip())
                        break
                    except ValueError:
                        pass
                time.sleep(0.05)
            assert child_pid is not None, "Child worker failed to signal readiness"

            # Main process attempts to acquire lock immediately -> must raise LockContentionError
            main_lock = WindowsWorkerLock(data_root)
            with pytest.raises(LockContentionError) as exc_info:
                main_lock.acquire_lock(owner_kind=OwnerKind.GENERATION, timeout_seconds=0.0)

            assert exc_info.value.details["holding_pid"] == child_pid

        finally:
            proc.terminate()
            proc.wait(timeout=5.0)

    def test_killed_owner_releases_os_lock_cleanly(self, tmp_path: Path) -> None:
        data_root = tmp_path / "KilledWorkerStore"
        ready_file = tmp_path / "killed_worker_ready.txt"
        worker_script = Path(__file__).resolve().parent.parent / "fakes" / "lock_worker.py"

        proc = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "--data-root",
                str(data_root),
                "--owner-kind",
                "search",
                "--hold-seconds",
                "30.0",  # Long hold time
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        child_pid = None
        try:
            for _ in range(50):
                if ready_file.is_file() and ready_file.stat().st_size > 0:
                    try:
                        child_pid = int(ready_file.read_text(encoding="utf-8").strip())
                        break
                    except ValueError:
                        pass
                time.sleep(0.05)
            assert child_pid is not None

            # Forcibly kill child worker process (SIGKILL equivalent)
            try:
                os.kill(child_pid, 9)
            except OSError:
                pass
            proc.kill()
            proc.wait(timeout=5.0)

            # OS must have released file lock immediately upon process death
            main_lock = WindowsWorkerLock(data_root)
            with main_lock.acquire(owner_kind=OwnerKind.SEARCH, timeout_seconds=0.5) as token:
                assert token.is_released is False
                assert token.pid == os.getpid()

        finally:
            if proc.poll() is None:
                proc.kill()
