"""Native Windows exclusive process locking implementation (RUN-01-S02).

Enforces:
- Single active worker (search, generation, or maintenance) per physical deployment data root.
- Native OS-held file byte lock (via msvcrt.locking on Windows; fcntl fallback on POSIX).
- Normalized physical data store paths across case variations and junction aliases.
- Diagnostic metadata (PID, owner kind, attempt UUID, acquired time) retained without lock file unlinking.
- Prompt failure with LockContentionError on contention.
- Automatic release on process death (SIGTERM, SIGKILL, crash).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from job_automation.orchestration.errors import LockAccessError, LockContentionError
from job_automation.orchestration.locking import normalize_lock_target
from job_automation.orchestration.records import OwnerKind

logger = logging.getLogger(__name__)

# Try import msvcrt for Windows; fcntl for POSIX
_HAS_MSVCRT = False
try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    pass

_HAS_FCNTL = False
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    pass


class LockToken:
    """Represents an actively held exclusive worker lock."""

    def __init__(
        self,
        lock_path: Path,
        data_root: Path,
        owner_kind: OwnerKind,
        attempt_id: uuid.UUID | None,
        fd: int,
    ) -> None:
        self.lock_path = lock_path
        self.data_root = data_root
        self.owner_kind = owner_kind
        self.attempt_id = attempt_id
        self.fd = fd
        self.pid = os.getpid()
        self.acquired_at = datetime.now(timezone.utc)
        self.is_released = False

    def release(self) -> None:
        """Release the OS lock and close file descriptor."""
        if self.is_released:
            return

        try:
            if _HAS_MSVCRT:
                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError as exc:
                    logger.debug("Error releasing msvcrt lock: %s", exc)
            elif _HAS_FCNTL:
                try:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
                except OSError as exc:
                    logger.debug("Error releasing fcntl lock: %s", exc)

            os.close(self.fd)
        except OSError as exc:
            logger.debug("Error closing lock fd: %s", exc)
        finally:
            self.is_released = True


class WindowsWorkerLock:
    """Exclusive process lock manager for a deployment data root."""

    LOCK_FILENAME = ".deployment.lock"
    DIAG_FILENAME = ".deployment.lock.diag"

    def __init__(self, data_root: str | Path) -> None:
        self.data_root = normalize_lock_target(data_root)
        self.lock_path = self.data_root / self.LOCK_FILENAME
        self.diag_path = self.data_root / self.DIAG_FILENAME

    def _read_diag_info(self) -> dict[str, Any]:
        """Read diagnostic metadata written by current or prior lock holder."""
        if not self.diag_path.is_file():
            return {}
        try:
            content = self.diag_path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return {}

    def _write_diag_info(self, owner_kind: OwnerKind, attempt_id: uuid.UUID | None) -> None:
        """Record diagnostic metadata about the current lock holder."""
        diag = {
            "pid": os.getpid(),
            "owner_kind": owner_kind.value,
            "attempt_id": str(attempt_id) if attempt_id else None,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "data_root": str(self.data_root),
        }
        try:
            self.diag_path.write_text(json.dumps(diag, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write lock diagnostic file: %s", exc)

    def _try_lock_fd(self, fd: int) -> bool:
        """Attempt to acquire a non-blocking exclusive byte lock on file descriptor."""
        if _HAS_MSVCRT:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBRLCK, 1)
                return True
            except (OSError, PermissionError):
                return False
        elif _HAS_FCNTL:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except (OSError, IOError):
                return False
        else:
            raise RuntimeError("Neither msvcrt nor fcntl is available for process locking")

    def acquire_lock(
        self,
        owner_kind: OwnerKind = OwnerKind.SEARCH,
        attempt_id: uuid.UUID | None = None,
        timeout_seconds: float = 0.0,
        poll_interval: float = 0.05,
    ) -> LockToken:
        """Acquire an exclusive lock or raise LockContentionError if already held."""
        self.data_root.mkdir(parents=True, exist_ok=True)

        start_time = time.monotonic()
        fd: int | None = None

        while True:
            if fd is None:
                try:
                    fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o666)
                except PermissionError as exc:
                    diag = self._read_diag_info()
                    raise LockAccessError(
                        f"Access denied opening lock file at '{self.lock_path}': {exc}",
                        details={"data_root": str(self.data_root), "is_access_denied": True, **diag},
                    ) from exc
                except OSError as exc:
                    diag = self._read_diag_info()
                    raise LockAccessError(
                        f"Failed to open lock file at '{self.lock_path}': {exc}",
                        details={"data_root": str(self.data_root), "is_access_denied": True, **diag},
                    ) from exc

            if self._try_lock_fd(fd):
                # Lock acquired successfully
                self._write_diag_info(owner_kind, attempt_id)
                token = LockToken(
                    lock_path=self.lock_path,
                    data_root=self.data_root,
                    owner_kind=owner_kind,
                    attempt_id=attempt_id,
                    fd=fd,
                )
                return token

            # Lock is currently held by another process
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout_seconds:
                # Contention: Close our un-locked fd and report diagnostic info
                try:
                    os.close(fd)
                except OSError:
                    pass

                diag = self._read_diag_info()
                holding_pid = diag.get("pid")
                holding_kind = diag.get("owner_kind", "unknown")
                holding_attempt = diag.get("attempt_id")

                msg = (
                    f"Deployment at '{self.data_root}' is already locked by an active process "
                    f"(PID={holding_pid}, kind='{holding_kind}', attempt='{holding_attempt}'). "
                    f"Concurrent execution on the same data store is prohibited."
                )
                raise LockContentionError(
                    msg,
                    details={
                        "data_root": str(self.data_root),
                        "lock_path": str(self.lock_path),
                        "holding_pid": holding_pid,
                        "holding_kind": holding_kind,
                        "holding_attempt": holding_attempt,
                    },
                )

            time.sleep(poll_interval)

    @contextmanager
    def acquire(
        self,
        owner_kind: OwnerKind = OwnerKind.SEARCH,
        attempt_id: uuid.UUID | None = None,
        timeout_seconds: float = 0.0,
    ) -> Generator[LockToken, None, None]:
        """Context manager for acquiring and safely releasing the exclusive lock."""
        token = self.acquire_lock(
            owner_kind=owner_kind,
            attempt_id=attempt_id,
            timeout_seconds=timeout_seconds,
        )
        try:
            yield token
        finally:
            token.release()

