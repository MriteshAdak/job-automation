"""Unit tests for subprocess launcher (AUTO-01-T03, T06, T11)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from job_automation.operations.scheduling.launcher import SubprocessLauncher, sanitize_text


def test_sanitize_text():
    """T11: Secrets and passwords in console text are redacted."""
    raw = "Connecting to postgresql://user:super_secret_pass@127.0.0.1:5432/db with token: my_secret_token_123"
    sanitized = sanitize_text(raw)
    assert "super_secret_pass" not in sanitized
    assert "my_secret_token_123" not in sanitized
    assert "[REDACTED]" in sanitized


def test_launch_python_version():
    """T03: Launcher executes absolute Python binary and captures output."""
    launcher = SubprocessLauncher()
    res = launcher.launch(["-c", "import sys; print(f'PY_VERSION:{sys.version_info.major}.{sys.version_info.minor}')"])
    assert res.exit_code == 0
    assert res.outcome == "success"
    assert "PY_VERSION:" in res.stdout


def test_launch_exit_code_propagation():
    """T11: Subprocess exit codes (0, 2, 3, 4) map correctly to domain outcomes."""
    launcher = SubprocessLauncher()

    # Code 0 -> success
    res0 = launcher.launch(["-c", "import sys; sys.exit(0)"])
    assert res0.exit_code == 0
    assert res0.outcome == "success"

    # Code 2 -> invalid_preflight
    res2 = launcher.launch(["-c", "import sys; sys.exit(2)"])
    assert res2.exit_code == 2
    assert res2.outcome == "invalid_preflight"

    # Code 3 -> busy
    res3 = launcher.launch(["-c", "import sys; sys.exit(3)"])
    assert res3.exit_code == 3
    assert res3.outcome == "busy"

    # Code 4 -> partial
    res4 = launcher.launch(["-c", "import sys; sys.exit(4)"])
    assert res4.exit_code == 4
    assert res4.outcome == "partial"


def test_launch_json_payload_and_run_id_extraction():
    """T11: Emitted JSON output is parsed and UUID extracted."""
    launcher = SubprocessLauncher()
    code = (
        "import json, sys\n"
        "print(json.dumps({'run_id': '11111111-2222-3333-4444-555555555555', 'status': 'success'}))\n"
        "sys.exit(0)\n"
    )
    res = launcher.launch(["-c", code])
    assert res.exit_code == 0
    assert res.json_payload is not None
    assert str(res.run_id) == "11111111-2222-3333-4444-555555555555"


def test_launch_timeout():
    """T10: Subprocess timeout kills child and reports timeout outcome."""
    launcher = SubprocessLauncher()
    res = launcher.launch(["-c", "import time; time.sleep(10)"], timeout_seconds=0.3)
    assert res.is_timeout is True
    assert res.outcome == "timeout"
    assert res.exit_code == 124

