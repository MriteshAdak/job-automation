"""Startup and failure recovery for local index staging and active state reconciliation."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from job_automation.context.index_files import verify_generation_files
from job_automation.contracts.retrieval_index import IndexManifest
from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexRecoveryManager:
    """Reconciles persisted database pointers and local filesystem index artifacts."""

    def __init__(
        self,
        indexes_dir: Path | str,
        repository: ContextIndexRepository,
    ) -> None:
        self.indexes_dir = Path(indexes_dir)
        self.repository = repository

    def reconcile(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
    ) -> dict[str, Any]:
        """Perform recovery checks on startup or after unexpected process restarts:

        1. Clean up orphaned staging directories.
        2. Verify active generation integrity; mark corrupt if files are missing or modified.
        3. Transition lingering 'staged' database records to 'failed'.
        """
        staging_cleaned: list[str] = []
        corrupt_generations: list[str] = []
        active_verified = False

        # 1. Clean up orphaned staging directories
        candidate_purpose_dir = self.indexes_dir / str(candidate_id) / purpose
        if candidate_purpose_dir.exists():
            for child in candidate_purpose_dir.iterdir():
                if child.is_dir() and child.name.startswith("staging_"):
                    try:
                        shutil.rmtree(child, ignore_errors=True)
                        staging_cleaned.append(child.name)
                    except Exception:
                        pass

        # 2. Check active generation integrity
        active_record = self.repository.get_active_generation(candidate_id, purpose)
        if active_record is not None:
            active_gen_id = uuid.UUID(active_record["active_generation_id"])
            gen_dir = Path(active_record["generation_dir"])

            try:
                manifest = IndexManifest.model_validate_json(active_record["manifest_json"])
                verify_generation_files(gen_dir, manifest)
                active_verified = True
            except Exception:
                # Mark as corrupt so consumers refuse to read it
                self.repository.update_generation_status(active_gen_id, status="corrupt")
                corrupt_generations.append(str(active_gen_id))

        # 3. Mark lingering 'staged' records as failed
        staged_records = self.repository.list_generations(
            candidate_id=candidate_id,
            purpose=purpose,
            status="staged",
        )
        for s in staged_records:
            self.repository.update_generation_status(
                uuid.UUID(s["generation_id"]), status="failed"
            )

        return {
            "staging_cleaned": staging_cleaned,
            "active_verified": active_verified,
            "corrupt_generations": corrupt_generations,
        }

