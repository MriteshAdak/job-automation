"""Native Windows subprocess tests: process mutual exclusion, exit code 3 on contention, and kill recovery (GEN-01-S03)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock


class TestWindowsSubprocessRestart:
    def test_search_lock_blocks_generation_worker_with_exit_code_3(
        self, tmp_path: Path
    ) -> None:
        data_root = tmp_path / "SubprocessLock ä"
        ready_file = tmp_path / "search_worker_ready.txt"
        lock_script = Path(__file__).resolve().parent.parent / "fakes" / "lock_worker.py"

        # 1. Start search worker child process holding lock for 5 seconds
        search_proc = subprocess.Popen(
            [
                sys.executable,
                str(lock_script),
                "--data-root",
                str(data_root),
                "--owner-kind",
                "search",
                "--hold-seconds",
                "5.0",
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            # Wait for search worker to signal readiness
            child_pid = None
            for _ in range(50):
                if ready_file.is_file() and ready_file.stat().st_size > 0:
                    try:
                        child_pid = int(ready_file.read_text(encoding="utf-8").strip())
                        break
                    except ValueError:
                        pass
                time.sleep(0.05)
            assert child_pid is not None, "Search worker failed to acquire lock"

            # 2. Launch generation worker subprocess while search worker holds lock
            gen_proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "job_automation",
                    "generation",
                    "work",
                    "--once",
                    "--data-root",
                    str(data_root),
                ],
                capture_output=True,
                text=True,
            )

            # 3. Assert generation worker exits with code 3 (Lock contention)
            assert gen_proc.returncode == 3
            assert "Exit Code:            3" in gen_proc.stdout or "busy" in gen_proc.stdout or "Deployment worker lock busy" in gen_proc.stdout

        finally:
            search_proc.terminate()
            search_proc.wait(timeout=5.0)

    def test_killed_worker_releases_lock_allowing_generation_worker_to_proceed(
        self, tmp_path: Path
    ) -> None:
        data_root = tmp_path / "SubprocessKill ä"
        ready_file = tmp_path / "killed_ready.txt"
        lock_script = Path(__file__).resolve().parent.parent / "fakes" / "lock_worker.py"

        # 1. Start worker holding lock indefinitely
        proc = subprocess.Popen(
            [
                sys.executable,
                str(lock_script),
                "--data-root",
                str(data_root),
                "--owner-kind",
                "generation",
                "--hold-seconds",
                "60.0",
                "--ready-file",
                str(ready_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            child_pid = None
            for _ in range(50):
                if ready_file.is_file() and ready_file.stat().st_size > 0:
                    try:
                        child_pid = int(ready_file.read_text(encoding="utf-8").strip())
                        break
                    except ValueError:
                        pass
                time.sleep(0.05)
            assert child_pid is not None

            # 2. Forcibly kill holding process
            try:
                os.kill(child_pid, 9)
            except OSError:
                pass
            proc.kill()
            proc.wait(timeout=5.0)

            # 3. Launch generation lock worker; OS must have released file lock immediately
            gen_proc = subprocess.run(
                [
                    sys.executable,
                    str(lock_script),
                    "--data-root",
                    str(data_root),
                    "--owner-kind",
                    "generation",
                    "--hold-seconds",
                    "0.1",
                ],
                capture_output=True,
                text=True,
            )

            # Must succeed (exit code 0 after acquiring lock)
            assert gen_proc.returncode == 0

        finally:
            if proc.poll() is None:
                proc.kill()
