"""Tests for RUN-01-S02 worker locking logic and edge cases."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.locking import normalize_lock_target
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import WindowsWorkerLock


class TestWorkerLocking:
    def test_single_process_acquire_and_release(self, tmp_path: Path) -> None:
        data_root = tmp_path / "Data Store Space ä"
        lock = WindowsWorkerLock(data_root)

        attempt_id = uuid.uuid4()
        with lock.acquire(owner_kind=OwnerKind.SEARCH, attempt_id=attempt_id) as token:
            assert token.is_released is False
            assert token.lock_path.is_file()
            diag = lock._read_diag_info()
            assert diag.get("pid") == os.getpid()
            assert diag.get("owner_kind") == "search"
            assert diag.get("attempt_id") == str(attempt_id)

        assert token.is_released is True
        # Lock file remains on disk (never unlinked)
        assert token.lock_path.is_file()

        # Re-acquisition succeeds immediately
        with lock.acquire(owner_kind=OwnerKind.GENERATION) as token2:
            assert token2.is_released is False

    def test_double_acquire_in_same_process_raises_contention(self, tmp_path: Path) -> None:
        data_root = tmp_path / "Data Store"
        lock1 = WindowsWorkerLock(data_root)
        lock2 = WindowsWorkerLock(data_root)

        with lock1.acquire(owner_kind=OwnerKind.SEARCH):
            with pytest.raises(LockContentionError) as exc_info:
                lock2.acquire_lock(owner_kind=OwnerKind.SEARCH, timeout_seconds=0.0)

            assert "already locked" in str(exc_info.value)
            assert exc_info.value.details["holding_pid"] == os.getpid()
            assert exc_info.value.details["holding_kind"] == "search"

    def test_search_and_generation_contend_on_same_store(self, tmp_path: Path) -> None:
        data_root = tmp_path / "SharedStore"
        lock = WindowsWorkerLock(data_root)

        with lock.acquire(owner_kind=OwnerKind.SEARCH):
            # Future GEN-01 worker attempting to acquire must fail promptly
            with pytest.raises(LockContentionError):
                lock.acquire_lock(owner_kind=OwnerKind.GENERATION, timeout_seconds=0.0)

    def test_independent_stores_do_not_contend(self, tmp_path: Path) -> None:
        store1 = tmp_path / "Store1"
        store2 = tmp_path / "Store2"
        lock1 = WindowsWorkerLock(store1)
        lock2 = WindowsWorkerLock(store2)

        with lock1.acquire(owner_kind=OwnerKind.SEARCH):
            # lock2 on different store succeeds
            with lock2.acquire(owner_kind=OwnerKind.SEARCH):
                pass

    def test_path_normalization_handles_relative_and_case(self, tmp_path: Path) -> None:
        store = tmp_path / "NormalizedStore"
        store.mkdir(parents=True)
        norm1 = normalize_lock_target(store)
        norm2 = normalize_lock_target(str(store).upper() if os.name == "nt" else store)
        assert norm1 == norm2

