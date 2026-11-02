"""Tests for Windows path handling, Unicode paths, and restart persistence (SFCLIENT-01-S07)."""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from job_automation.salesforce.credentials import WindowsDpapiCredentialStore


def test_windows_dpapi_unicode_and_space_path(tmp_path: Path) -> None:
    """Verify Windows DPAPI credential store works in directories with spaces and umlauts."""
    unicode_dir = tmp_path / "Job Automation Prüfung ä" / "Benutzer Daten" / "credentials"
    store = WindowsDpapiCredentialStore(unicode_dir)

    secret = "refresh_token_unicode_prüfung_123"
    ref = "salesforce/refresh_token"

    store.set_credential(ref, secret)

    # Verify decrypt
    assert store.get_credential(ref) == secret

    # Re-instantiate store to simulate process restart
    reopened_store = WindowsDpapiCredentialStore(unicode_dir)
    assert reopened_store.get_credential(ref) == secret


def test_working_directory_independence(tmp_path: Path) -> None:
    """Verify credential store operations succeed regardless of current working directory."""
    original_cwd = os.getcwd()
    cred_dir = (tmp_path / "cred_storage").resolve()
    store = WindowsDpapiCredentialStore(cred_dir)

    try:
        # Change working directory to temp dir
        os.chdir(tmp_path)

        secret = "wd_independent_secret_abc"
        ref = "salesforce/token"
        store.set_credential(ref, secret)
        assert store.get_credential(ref) == secret
    finally:
        os.chdir(original_cwd)

