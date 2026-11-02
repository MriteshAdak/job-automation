"""Protected credential storage on native Windows (SFCLIENT-01-S03).

Provides:
- Native Windows DPAPI (CryptProtectData / CryptUnprotectData) encrypted storage.
- Atomic file operations preventing half-written or corrupted secrets.
- In-memory mock store for unit testing.
- Single-use refresh token exchange-in-progress state tracking.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
from ctypes import wintypes
from pathlib import Path
from typing import Any

from job_automation.salesforce.ports import CredentialStore


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _dpapi_protect(data: bytes, description: str = "SalesforceCredential") -> bytes:
    """Encrypt byte string using Windows DPAPI CryptProtectData."""
    if not hasattr(ctypes, "windll") or not hasattr(ctypes.windll, "crypt32"):
        raise RuntimeError("Windows DPAPI (crypt32.dll) is not available on this platform.")

    in_blob = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
    )
    out_blob = DATA_BLOB()

    res = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not res:
        err = ctypes.GetLastError()
        raise RuntimeError(f"CryptProtectData failed with Windows error code {err}.")

    try:
        encrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return encrypted_bytes
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt byte string using Windows DPAPI CryptUnprotectData."""
    if not hasattr(ctypes, "windll") or not hasattr(ctypes.windll, "crypt32"):
        raise RuntimeError("Windows DPAPI (crypt32.dll) is not available on this platform.")

    in_blob = DATA_BLOB(
        len(data),
        ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_byte)),
    )
    out_blob = DATA_BLOB()

    res = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not res:
        err = ctypes.GetLastError()
        raise RuntimeError(f"CryptUnprotectData failed with Windows error code {err}.")

    try:
        decrypted_bytes = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return decrypted_bytes
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _ref_to_filename(ref: str) -> str:
    """Map opaque credential reference into a safe filename."""
    # Sanitize reference string for safe filesystem usage
    safe_slug = re.sub(r"[^A-Za-z0-9_-]", "_", ref).strip("_")
    h = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]
    return f"{safe_slug}_{h}.bin"


class WindowsDpapiCredentialStore:
    """Protected Windows credential store using native DPAPI."""

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, ref: str) -> Path:
        return self.storage_dir / _ref_to_filename(ref)

    def _progress_marker_path(self, ref: str) -> Path:
        return self.storage_dir / f"{_ref_to_filename(ref)}.exchange_pending"

    def get_credential(self, ref: str) -> str | None:
        """Retrieve and decrypt protected credential."""
        p = self._file_path(ref)
        if not p.is_file():
            return None
        try:
            with open(p, "rb") as f:
                encrypted = f.read()
            decrypted = _dpapi_unprotect(encrypted)
            return decrypted.decode("utf-8")
        except Exception as err:
            raise RuntimeError(f"Failed to decrypt protected credential '{ref}': {err}") from err

    def set_credential(self, ref: str, value: str) -> None:
        """Encrypt and atomically store protected credential."""
        if not isinstance(value, str):
            raise ValueError("Credential value must be a string.")
        p = self._file_path(ref)
        encrypted = _dpapi_protect(value.encode("utf-8"))

        # Atomic write via temporary file
        tmp_path = p.with_suffix(".tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(encrypted)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, p)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def delete_credential(self, ref: str) -> None:
        """Delete credential file if present."""
        p = self._file_path(ref)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
        self.clear_exchange_in_progress(ref)

    def is_exchange_in_progress(self, ref: str) -> bool:
        """Check whether single-use token exchange was left unfinalized."""
        return self._progress_marker_path(ref).exists()

    def mark_exchange_in_progress(self, ref: str) -> None:
        """Persist state marker before sending single-use refresh token."""
        marker = self._progress_marker_path(ref)
        with open(marker, "wb") as f:
            f.write(b"1")
            f.flush()
            os.fsync(f.fileno())

    def clear_exchange_in_progress(self, ref: str) -> None:
        """Remove state marker after successful token commit."""
        marker = self._progress_marker_path(ref)
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass


class InMemoryCredentialStore:
    """In-memory credential store for tests and synthetic execution."""

    def __init__(self, initial_data: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(initial_data or {})
        self._exchange_in_progress: set[str] = set()

    def get_credential(self, ref: str) -> str | None:
        return self._data.get(ref)

    def set_credential(self, ref: str, value: str) -> None:
        self._data[ref] = value

    def delete_credential(self, ref: str) -> None:
        self._data.pop(ref, None)
        self._exchange_in_progress.discard(ref)

    def is_exchange_in_progress(self, ref: str) -> bool:
        return ref in self._exchange_in_progress

    def mark_exchange_in_progress(self, ref: str) -> None:
        self._exchange_in_progress.add(ref)

    def clear_exchange_in_progress(self, ref: str) -> None:
        self._exchange_in_progress.discard(ref)

