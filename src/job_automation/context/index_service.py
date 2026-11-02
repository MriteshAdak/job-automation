"""Public service facade for CONTEXT-03 local vector and keyword indexing."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from job_automation.context.index_builder import IndexBuilder
from job_automation.context.index_cleanup import IndexCleanupManager
from job_automation.context.index_errors import (
    map_index_exception_to_classified_error,
)
from job_automation.context.index_files import verify_generation_files
from job_automation.context.index_lifecycle import IndexLifecycleManager
from job_automation.context.index_ports import IndexHandlePort
from job_automation.context.index_reader import IndexStore
from job_automation.context.index_recovery import IndexRecoveryManager
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.retrieval_index import (
    IndexBuildRequest,
    IndexBuildResult,
    IndexManifest,
    IndexReadRequest,
)
from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexService:
    """Coordinating service facade for index construction, activation, reading, and cleanup."""

    def __init__(
        self,
        indexes_dir: Path | str,
        repository: ContextIndexRepository,
        provider: ModelProvider,
    ) -> None:
        self.indexes_dir = Path(indexes_dir)
        self.repository = repository
        self.provider = provider

        self.cleanup_mgr = IndexCleanupManager(repository=repository)
        self.lifecycle_mgr = IndexLifecycleManager(
            repository=repository, cleanup_manager=self.cleanup_mgr
        )
        self.recovery_mgr = IndexRecoveryManager(
            indexes_dir=self.indexes_dir, repository=repository
        )
        self.builder = IndexBuilder(
            indexes_dir=self.indexes_dir,
            provider=self.provider,
            repository=self.repository,
        )
        self.store = IndexStore(
            indexes_dir=self.indexes_dir,
            repository=self.repository,
        )

    def build(
        self,
        request: IndexBuildRequest,
        auto_activate: bool = False,
    ) -> tuple[IndexBuildResult | None, ClassifiedError | None]:
        """Construct a local index generation with optional immediate activation."""
        result, err = self.builder.build(request)
        if err is not None or result is None:
            return None, err

        if auto_activate:
            try:
                new_token = self.lifecycle_mgr.activate(
                    candidate_id=request.candidate_id,
                    purpose=request.purpose,
                    generation_id=result.generation_id,
                    expected_prior_token=request.expected_prior_token,
                    expected_profile_version=request.profile_version,
                )
                result = IndexBuildResult(
                    generation_id=result.generation_id,
                    manifest=result.manifest,
                    build_record=result.build_record,
                    activation_token=new_token,
                )
            except Exception as exc:
                return None, map_index_exception_to_classified_error(exc)

        return result, None

    def activate(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
        generation_id: uuid.UUID,
        expected_prior_token: str | None = None,
        expected_profile_version: str | None = None,
    ) -> tuple[str | None, ClassifiedError | None]:
        """Activate a ready generation."""
        try:
            token = self.lifecycle_mgr.activate(
                candidate_id=candidate_id,
                purpose=purpose,
                generation_id=generation_id,
                expected_prior_token=expected_prior_token,
                expected_profile_version=expected_profile_version,
            )
            return token, None
        except Exception as exc:
            return None, map_index_exception_to_classified_error(exc)

    def open(
        self,
        request: IndexReadRequest,
    ) -> tuple[IndexHandlePort | None, ClassifiedError | None]:
        """Open a verified read-only handle."""
        return self.store.open(request)

    def status(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
    ) -> dict[str, Any]:
        """Return diagnostic status of active and recent index generations."""
        active = self.repository.get_active_generation(candidate_id, purpose)
        recent = self.repository.list_generations(candidate_id, purpose=purpose)

        return {
            "candidate_id": str(candidate_id),
            "purpose": purpose,
            "has_active": active is not None,
            "active_generation_id": active["active_generation_id"] if active else None,
            "active_profile_version": active["profile_version"] if active else None,
            "active_row_count": active["row_count"] if active else 0,
            "active_dimension": active["dimension"] if active else 0,
            "recent_generation_count": len(recent),
            "recent_generations": [
                {
                    "generation_id": r["generation_id"],
                    "status": r["status"],
                    "profile_version": r["profile_version"],
                    "created_at": r["created_at"],
                }
                for r in recent[:5]
            ],
        }

    def verify(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
    ) -> tuple[bool, str]:
        """Verify on-disk file integrity and manifest hashes for the active generation."""
        active = self.repository.get_active_generation(candidate_id, purpose)
        if active is None:
            return False, "No active index generation found"

        gen_dir = Path(active["generation_dir"])
        try:
            manifest = IndexManifest.model_validate_json(active["manifest_json"])
            verify_generation_files(gen_dir, manifest)
            return True, f"Active generation '{active['active_generation_id']}' verified on disk"
        except Exception as exc:
            return False, f"Verification failed: {exc}"

    def cleanup(
        self,
        candidate_id: uuid.UUID,
        purpose: str | None = None,
        retention_count: int | None = None,
    ) -> dict[str, Any]:
        """Trigger cleanup of unpinned retired generations."""
        return self.cleanup_mgr.cleanup(
            candidate_id=candidate_id,
            purpose=purpose,
            retention_count=retention_count,
        )

    def reconcile(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
    ) -> dict[str, Any]:
        """Run startup / crash recovery checks."""
        return self.recovery_mgr.reconcile(candidate_id=candidate_id, purpose=purpose)

