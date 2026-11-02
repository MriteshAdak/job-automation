"""Clean native subprocess launcher for CLI commands (AUTO-01-S03, S05, S06).

Enforces:
- Structured argument lists (no shell string concatenation or command injection).
- Absolute Python executable and explicit working directory.
- Sanitized environment passing.
- Bounded timeout with process-tree termination.
- Bounded stdout/stderr capture with secret redaction.
- Structured exit code mapping to domain outcomes.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Pattern to redact tokens / passwords from logs and captured output
REDACT_PATTERNS = [
    re.compile(r"://([^:@]+):([^@]+)@"),
    re.compile(r"(password|token|secret|client_secret)[\"']?\s*[:=]\s*[\"']?([^\s\"',}]+)", re.IGNORECASE),
]


def sanitize_text(text: str | None) -> str:
    """Redact passwords and secrets from captured console output."""
    if not text:
        return ""
    sanitized = text
    for pattern in REDACT_PATTERNS:
        sanitized = pattern.sub(r"\1:[REDACTED]@", sanitized)
    return sanitized


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of a CLI subprocess execution."""

    exit_code: int
    outcome: str
    pid: int | None
    stdout: str
    stderr: str
    json_payload: dict[str, Any] | None = None
    run_id: uuid.UUID | None = None
    is_timeout: bool = False
    duration_seconds: float = 0.0


class SubprocessLauncher:
    """Executes existing Python CLI commands via native Windows subprocesses."""

    def __init__(
        self,
        python_executable: Path | str | None = None,
        working_dir: Path | str | None = None,
    ) -> None:
        if python_executable:
            self.python_exe = Path(python_executable).resolve()
        else:
            self.python_exe = Path(sys.executable).resolve()

        if not self.python_exe.is_file():
            raise FileNotFoundError(f"Python executable not found at '{self.python_exe}'")

        self.cwd = Path(working_dir).resolve() if working_dir else Path.cwd().resolve()

    def launch(
        self,
        args: list[str],
        timeout_seconds: float = 3600.0,
        extra_env: dict[str, str] | None = None,
    ) -> LaunchResult:
        """Launch a command using structured argument list."""
        cmd = [str(self.python_exe)] + args

        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        if extra_env:
            env.update(extra_env)

        start_time = time.monotonic()
        proc = None
        is_timeout = False
        raw_stdout = ""
        raw_stderr = ""
        exit_code = 1

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(self.cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            try:
                stdout_str, stderr_str = proc.communicate(timeout=timeout_seconds)
                exit_code = proc.returncode
                raw_stdout = stdout_str or ""
                raw_stderr = stderr_str or ""
            except subprocess.TimeoutExpired:
                is_timeout = True
                exit_code = 124
                logger.warning("Subprocess timed out after %.1fs; terminating process tree...", timeout_seconds)
                proc.kill()
                stdout_str, stderr_str = proc.communicate()
                raw_stdout = stdout_str or ""
                raw_stderr = stderr_str or ""

        except KeyboardInterrupt:
            if proc:
                proc.kill()
                stdout_str, stderr_str = proc.communicate()
                raw_stdout = stdout_str or ""
                raw_stderr = stderr_str or ""
            return LaunchResult(
                exit_code=130,
                outcome="interrupted",
                pid=proc.pid if proc else None,
                stdout=sanitize_text(raw_stdout[:65536]),
                stderr=sanitize_text(raw_stderr[:65536]),
                duration_seconds=time.monotonic() - start_time,
            )
        except Exception as exc:
            return LaunchResult(
                exit_code=1,
                outcome="failed",
                pid=None,
                stdout="",
                stderr=sanitize_text(str(exc)),
                duration_seconds=time.monotonic() - start_time,
            )

        duration = time.monotonic() - start_time
        pid = proc.pid if proc else None

        # Sanitize and truncate output to 64KB tails
        clean_stdout = sanitize_text(raw_stdout)
        clean_stderr = sanitize_text(raw_stderr)
        stdout_tail = clean_stdout[-65536:] if len(clean_stdout) > 65536 else clean_stdout
        stderr_tail = clean_stderr[-65536:] if len(clean_stderr) > 65536 else clean_stderr

        # Attempt to parse structured JSON from stdout
        json_payload = None
        run_id = None
        if clean_stdout.strip():
            # Try full body as json
            try:
                json_payload = json.loads(clean_stdout.strip())
            except Exception:
                # Look for JSON object in output lines
                lines = clean_stdout.strip().splitlines()
                for line in reversed(lines):
                    line_str = line.strip()
                    if line_str.startswith("{") and line_str.endswith("}"):
                        try:
                            json_payload = json.loads(line_str)
                            break
                        except Exception:
                            pass

        if json_payload and isinstance(json_payload, dict):
            # Extract run ID or request ID
            raw_run = (
                json_payload.get("run_id")
                or json_payload.get("c15_summary", {}).get("run_id")
                or json_payload.get("request_id")
            )
            if raw_run:
                try:
                    run_id = uuid.UUID(str(raw_run))
                except Exception:
                    pass

        # Classify exit code to domain outcome
        if is_timeout:
            outcome = "timeout"
        elif exit_code == 0:
            outcome = "success"
        elif exit_code == 2:
            outcome = "invalid_preflight"
        elif exit_code == 3:
            outcome = "busy"
        elif exit_code == 4:
            outcome = "partial"
        elif exit_code == 130:
            outcome = "interrupted"
        else:
            outcome = "failed"

        return LaunchResult(
            exit_code=exit_code,
            outcome=outcome,
            pid=pid,
            stdout=stdout_tail,
            stderr=stderr_tail,
            json_payload=json_payload,
            run_id=run_id,
            is_timeout=is_timeout,
            duration_seconds=duration,
        )

