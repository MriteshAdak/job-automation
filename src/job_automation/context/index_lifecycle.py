"""Lifecycle management for atomic activation and compare-and-swap transitions."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from job_automation.context.index_cleanup import IndexCleanupManager
from job_automation.context.index_errors import (
    IndexBindingError,
    IndexStaleError,
    IndexValidationError,
)
from job_automation.context.index_files import verify_generation_files
from job_automation.contracts.retrieval_index import IndexManifest
from job_automation.storage.repositories.context_indexes import (
    ContextIndexRepository,
)


class IndexLifecycleManager:
    """Manages generation state transitions, compare-and-swap activation, and retirement."""

    def __init__(
        self,
        repository: ContextIndexRepository,
        cleanup_manager: IndexCleanupManager | None = None,
    ) -> None:
        self.repository = repository
        self.cleanup_manager = cleanup_manager

    def activate(
        self,
        candidate_id: uuid.UUID,
        purpose: str,
        generation_id: uuid.UUID,
        expected_prior_token: str | None = None,
        expected_profile_version: str | None = None,
    ) -> str:
        """Atomically activate an index generation for the given candidate and purpose.

        Checks:
        - Target generation exists and is in 'ready' or 'staged' status.
        - Target profile_version matches expected_profile_version (if provided).
        - Payload files on disk exist and match manifest digests.
        - Prior activation token matches expected_prior_token (if provided).

        Returns:
        - new activation_token
        """
        gen = self.repository.get_generation(generation_id)
        if gen is None:
            raise IndexValidationError(
                f"Index generation '{generation_id}' not found",
                field_path="generation_id",
            )

        if gen["status"] not in ("ready", "staged"):
            raise IndexBindingError(
                f"Generation '{generation_id}' has status '{gen['status']}'; cannot activate",
                field_path="status",
                details={"generation_id": str(generation_id), "status": gen["status"]},
            )

        if expected_profile_version is not None:
            if gen["profile_version"] != expected_profile_version:
                raise IndexStaleError(
                    f"Generation profile version '{gen['profile_version']}' does not match expected '{expected_profile_version}'",
                    field_path="profile_version",
                    details={
                        "generation_version": gen["profile_version"],
                        "expected_version": expected_profile_version,
                    },
                )

        # Verify files on disk before promoting to active
        gen_dir = Path(gen["generation_dir"])
        manifest = IndexManifest.model_validate_json(gen["manifest_json"])
        verify_generation_files(gen_dir, manifest)

        # Transactionally perform compare-and-swap activation in repository
        activation_token = str(uuid.uuid4())
        self.repository.set_active_generation(
            candidate_id=candidate_id,
            purpose=purpose,
            generation_id=generation_id,
            profile_version=gen["profile_version"],
            activation_token=activation_token,
            expected_prior_token=expected_prior_token,
        )

        # Trigger cleanup of unpinned retired generations if cleanup manager configured
        if self.cleanup_manager is not None:
            try:
                self.cleanup_manager.cleanup(candidate_id=candidate_id, purpose=purpose)
            except Exception:
                pass  # Non-fatal if cleanup has delayed file locks

        return activation_token

