"""Evaluation workspace management and database isolation (EVAL-01-S03).

Enforces:
- Runtime evaluation paths reside in an explicit, isolated directory.
- Strict database aliasing prevention (verifies eval DB != production DB).
- Windows path normalization (handles casing, unicode, spaces, and junctions).
"""

from __future__ import annotations

import os
from pathlib import Path

from job_automation.evaluation.errors import DatabaseAliasingError
from job_automation.evaluation.settings import DEFAULT_EVAL_DB_NAME, EvaluationSettings


class EvaluationWorkspace:
    """Manages the isolated evaluation runtime directory structure and storage locations."""

    def __init__(self, eval_root: Path | str, production_db_path: Path | str | None = None) -> None:
        self.eval_root = Path(eval_root).resolve()
        if not self.eval_root.is_absolute():
            raise ValueError(f"Evaluation workspace root must be absolute, got: '{eval_root}'")

        self.db_path = (self.eval_root / DEFAULT_EVAL_DB_NAME).resolve()
        self.artifacts_dir = (self.eval_root / "artifacts").resolve()
        self.packets_dir = (self.eval_root / "review_packets").resolve()
        self.reports_dir = (self.eval_root / "reports").resolve()

        self.production_db_path: Path | None = (
            Path(production_db_path).resolve() if production_db_path is not None else None
        )

        self._check_aliasing()

    @classmethod
    def from_settings(cls, settings: EvaluationSettings) -> EvaluationWorkspace:
        """Construct workspace from validated EvaluationSettings."""
        return cls(
            eval_root=settings.eval_root,
            production_db_path=settings.production_db_path,
        )

    def initialize_directories(self) -> None:
        """Create workspace directories on demand."""
        self.eval_root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.packets_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _check_aliasing(self) -> None:
        """Prevent collision or aliasing between evaluation DB and production DB."""
        if self.production_db_path is None:
            return

        eval_norm = os.path.normcase(os.path.abspath(str(self.db_path)))
        prod_norm = os.path.normcase(os.path.abspath(str(self.production_db_path)))

        if eval_norm == prod_norm:
            raise DatabaseAliasingError(
                f"Evaluation database path '{self.db_path}' aliases production database path "
                f"'{self.production_db_path}'. Evaluation storage must be strictly isolated."
            )

        if self.db_path.exists() and self.production_db_path.exists():
            try:
                if os.path.samefile(self.db_path, self.production_db_path):
                    raise DatabaseAliasingError(
                        f"Evaluation database '{self.db_path}' and production database "
                        f"'{self.production_db_path}' resolve to the same underlying file."
                    )
            except OSError:
                pass

