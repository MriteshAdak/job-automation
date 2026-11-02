"""Bounded subprocess execution and native Windows process tree containment (GEN-05-S04)."""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def terminate_process_tree(pid: int, grace_seconds: int = 5) -> None:
    """Terminate a process and all its descendants on Windows using taskkill."""
    try:
        # /F: Forcefully terminate, /T: Terminate tree, /PID: Process ID
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=grace_seconds,
            check=False,
        )
    except Exception as exc:
        logger.warning("Could not terminate process tree for PID %s: %s", pid, exc)


def run_bounded_process(
    cmd: list[str],
    cwd: Path,
    timeout_seconds: int = 120,
    cleanup_grace_seconds: int = 10,
) -> tuple[int | None, str, str, bool]:
    """Run an external command with timeout and process-tree cleanup.

    Returns:
        (exit_code, stdout, stderr, timed_out)
    """
    start_time = time.monotonic()
    timed_out = False

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
    except Exception as exc:
        logger.error("Failed to launch process %s: %s", cmd[0] if cmd else "", exc)
        return None, "", str(exc), False

    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        logger.warning(
            "Process %s timed out after %s seconds; terminating tree (PID: %s)",
            cmd[0] if cmd else "",
            timeout_seconds,
            proc.pid,
        )
        terminate_process_tree(proc.pid, grace_seconds=cleanup_grace_seconds)
        try:
            stdout, stderr = proc.communicate(timeout=cleanup_grace_seconds)
        except Exception:
            stdout, stderr = "", "Process communication failed after timeout termination"
        exit_code = proc.returncode

    return exit_code, stdout, stderr, timed_out

