"""Tests for Windows DPAPI and in-memory credential stores (SFCLIENT-01-S03)."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.salesforce.credentials import (
    InMemoryCredentialStore,
    WindowsDpapiCredentialStore,
)


def test_in_memory_credential_store() -> None:
    """Verify basic CRUD and exchange marker operations in memory."""
    store = InMemoryCredentialStore({"initial/key": "val123"})
    assert store.get_credential("initial/key") == "val123"
    assert store.get_credential("missing/key") is None

    store.set_credential("salesforce/refresh_token", "rt_secret_abc")
    assert store.get_credential("salesforce/refresh_token") == "rt_secret_abc"

    assert not store.is_exchange_in_progress("salesforce/refresh_token")
    store.mark_exchange_in_progress("salesforce/refresh_token")
    assert store.is_exchange_in_progress("salesforce/refresh_token")

    store.clear_exchange_in_progress("salesforce/refresh_token")
    assert not store.is_exchange_in_progress("salesforce/refresh_token")

    store.delete_credential("salesforce/refresh_token")
    assert store.get_credential("salesforce/refresh_token") is None


def test_windows_dpapi_credential_store(tmp_path: Path) -> None:
    """Verify native Windows DPAPI encryption, decryption, and atomic storage."""
    cred_dir = tmp_path / "Job Automation Prüfung ä" / "credentials"
    store = WindowsDpapiCredentialStore(cred_dir)

    secret = "my_super_secret_refresh_token_xyz_123"
    ref = "salesforce/refresh_token"

    # Store secret
    store.set_credential(ref, secret)

    # Inspect file on disk directly
    file_path = store._file_path(ref)
    assert file_path.is_file()
    with open(file_path, "rb") as f:
        disk_bytes = f.read()

    # Verify bytes are encrypted and do not contain plaintext secret
    assert secret.encode("utf-8") not in disk_bytes
    assert disk_bytes != secret.encode("utf-8")

    # Decrypt via store
    retrieved = store.get_credential(ref)
    assert retrieved == secret

    # Exchange marker
    assert not store.is_exchange_in_progress(ref)
    store.mark_exchange_in_progress(ref)
    assert store.is_exchange_in_progress(ref)
    store.clear_exchange_in_progress(ref)
    assert not store.is_exchange_in_progress(ref)

    # Delete
    store.delete_credential(ref)
    assert store.get_credential(ref) is None
    assert not file_path.exists()

