"""Worker lock interfaces and abstractions for multi-process safety (RUN-01-S02)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.records import OwnerKind


def normalize_lock_target(data_root: str | Path) -> Path:
    """Normalize data store root path to guarantee single lock file per physical store.

    Handles case aliases, relative paths, and junction/symlink targets.
    """
    resolved = Path(data_root).resolve()
    normalized_str = os.path.realpath(str(resolved))
    if os.name == "nt":
        # Windows file system paths are case-insensitive
        normalized_str = os.path.normcase(normalized_str)
    return Path(normalized_str)
