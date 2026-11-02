"""Physical cleanup and retention enforcement for retired index generations."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexCleanupManager:
    """Safely cleans up retired, unpinned index payloads on local disk."""

    def __init__(
        self,
        repository: ContextIndexRepository,
        default_retention_count: int = 2,
    ) -> None:
        self.repository = repository
        self.default_retention_count = default_retention_count

    def cleanup(
        self,
        candidate_id: uuid.UUID,
        purpose: str | None = None,
        retention_count: int | None = None,
    ) -> dict[str, Any]:
        """Remove unpinned retired generation files exceeding retention allowance.

        Handles Windows file sharing violations gracefully by recording pending status
        instead of aborting.
        """
        keep_count = (
            retention_count if retention_count is not None else self.default_retention_count
        )

        generations = self.repository.list_generations(
            candidate_id=candidate_id,
            purpose=purpose,
            status="retired",
        )

        deleted: list[str] = []
        retained: list[str] = []
        pinned: list[str] = []
        pending_errors: list[dict[str, str]] = []

        unpinned_retired: list[dict[str, Any]] = []

        for gen in generations:
            gen_id = uuid.UUID(gen["generation_id"])
            if self.repository.is_generation_pinned(gen_id):
                pinned.append(str(gen_id))
            else:
                unpinned_retired.append(gen)

        # Retain the most recent `keep_count` unpinned retired generations
        for idx, gen in enumerate(unpinned_retired):
            gen_id = gen["generation_id"]
            gen_dir = Path(gen["generation_dir"])

            if idx < keep_count:
                retained.append(gen_id)
                continue

            # Remove directory from disk
            if gen_dir.exists():
                try:
                    shutil.rmtree(gen_dir)
                    deleted.append(gen_id)
                    self.repository.update_generation_status(uuid.UUID(gen_id), status="deleted")
                except (PermissionError, OSError) as exc:
                    pending_errors.append(
                        {
                            "generation_id": gen_id,
                            "error": f"Windows file lock or access error: {exc}",
                        }
                    )
            else:
                # Directory already gone
                deleted.append(gen_id)
                self.repository.update_generation_status(uuid.UUID(gen_id), status="deleted")

        return {
            "deleted": deleted,
            "retained": retained,
            "pinned": pinned,
            "errors": pending_errors,
        }

