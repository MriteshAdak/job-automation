"""Frozen retrieval index resolution, validation, pinning, and guarded reader adapter."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Sequence

from job_automation.context.index_files import verify_generation_files
from job_automation.context.index_ports import IndexHandlePort, IndexStorePort
from job_automation.context.index_reader import IndexHandle, IndexStore
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.retrieval_index import (
    IndexManifest,
    IndexReadRequest,
)
from job_automation.generation.input_errors import frozen_index_mismatch_error
from job_automation.storage.repositories.context_indexes import ContextIndexRepository


class FrozenIndexStoreAdapter(IndexStorePort):
    """Guarded IndexStorePort adapter enforcing request-bound pin and frozen generation bindings."""

    def __init__(
        self,
        indexes_dir: Path | str,
        repository: ContextIndexRepository,
        request_id: uuid.UUID,
        expected_candidate_id: uuid.UUID,
        expected_purpose: str,
        expected_profile_version: str,
        expected_snapshot_fingerprint: str,
        pinned_generation_id: uuid.UUID,
        pin_id: uuid.UUID,
    ) -> None:
        self.indexes_dir = Path(indexes_dir)
        self.repository = repository
        self.request_id = request_id
        self.expected_candidate_id = expected_candidate_id
        self.expected_purpose = expected_purpose
        self.expected_profile_version = expected_profile_version
        self.expected_snapshot_fingerprint = expected_snapshot_fingerprint
        self.pinned_generation_id = pinned_generation_id
        self.pin_id = pin_id
        self._underlying = IndexStore(indexes_dir=self.indexes_dir, repository=self.repository)

    def open(
        self,
        request: IndexReadRequest,
    ) -> tuple[IndexHandlePort | None, ClassifiedError | None]:
        """Open a verified read-only handle strictly for the pinned generation.

        Enforces:
        - Candidate identity, purpose, and profile version must match sealed values.
        - The generation must be pinned specifically for this request.
        - Prohibits active-pointer resolution or fallback to newest versions.
        """
        # Validate request matches expected sealed bindings
        if request.candidate_id != self.expected_candidate_id:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Candidate ID mismatch: request specifies {request.candidate_id}, sealed for {self.expected_candidate_id}",
                details={"reason_code": "frozen_index_mismatch"},
            )

        if request.purpose != self.expected_purpose:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Purpose mismatch: request specifies {request.purpose}, sealed for {self.expected_purpose}",
                details={"reason_code": "frozen_index_mismatch"},
            )

        # Check pin ownership and active status
        cursor = self.repository.conn.execute(
            """
            SELECT pin_id, generation_id, pinned_for, released_at
            FROM context_index_pins
            WHERE pin_id = ? AND generation_id = ? AND pinned_for = ? AND released_at IS NULL
            """,
            (str(self.pin_id), str(self.pinned_generation_id), str(self.request_id)),
        )
        pin_row = cursor.fetchone()
        if not pin_row:
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Request-owned index pin '{self.pin_id}' is not active or not authorized for request '{self.request_id}'",
                details={"reason_code": "frozen_index_mismatch"},
            )

        # Force frozen authorization mode and frozen generation ID
        read_req = IndexReadRequest(
            candidate_id=self.expected_candidate_id,
            purpose=self.expected_purpose,
            authorization_mode="frozen_use",
            frozen_generation_id=self.pinned_generation_id,
        )

        handle, err = self._underlying.open(read_req)
        if err or handle is None:
            return None, err

        # Additional verification on opened handle metadata
        manifest = handle.manifest
        if manifest.profile_version != self.expected_profile_version:
            handle.close()
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Index handle profile version mismatch: {manifest.profile_version} != {self.expected_profile_version}",
                details={"reason_code": "frozen_index_mismatch"},
            )

        if manifest.snapshot_fingerprint != self.expected_snapshot_fingerprint:
            handle.close()
            return None, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Index handle snapshot fingerprint mismatch: {manifest.snapshot_fingerprint} != {self.expected_snapshot_fingerprint}",
                details={"reason_code": "frozen_index_mismatch"},
            )

        return handle, None


def resolve_and_pin_rag_index(
    indexes_dir: Path | str,
    repository: ContextIndexRepository,
    request_id: uuid.UUID,
    candidate_id: uuid.UUID,
    purpose: str,
    profile_version: str,
    snapshot_fingerprint: str,
) -> tuple[uuid.UUID | None, uuid.UUID | None, ClassifiedError | None]:
    """Resolve a compatible RAG index generation and acquire a durable request-owned pin.

    Returns:
        tuple[pinned_generation_id, pin_id, error]
    """
    # 1. First check if active generation for candidate and purpose matches
    active = repository.get_active_generation(candidate_id, purpose)
    chosen_gen: dict | None = None

    if active and active.get("status") in ("ready", "active"):
        if (
            active.get("profile_version") == profile_version
            and active.get("snapshot_fingerprint") == snapshot_fingerprint
        ):
            chosen_gen = active

    # 2. If active doesn't match, inspect recent generations
    if chosen_gen is None:
        candidates = repository.list_generations(candidate_id, purpose=purpose)
        for gen in candidates:
            if gen.get("status") in ("ready", "active", "retired"):
                if (
                    gen.get("profile_version") == profile_version
                    and IndexManifest.model_validate_json(gen["manifest_json"]).snapshot_fingerprint == snapshot_fingerprint
                ):
                    chosen_gen = gen
                    break

    if chosen_gen is None:
        return None, None, frozen_index_mismatch_error(
            candidate_id=candidate_id,
            purpose=purpose,
            message=(
                f"No compatible RAG index found for candidate {candidate_id}, "
                f"purpose {purpose}, profile version {profile_version}"
            ),
        )

    gen_id = uuid.UUID(chosen_gen.get("generation_id") or chosen_gen["active_generation_id"])
    gen_dir = Path(chosen_gen["generation_dir"])
    manifest = IndexManifest.model_validate_json(chosen_gen["manifest_json"])

    # 3. Verify file integrity before pinning
    try:
        verify_generation_files(gen_dir, manifest)
    except Exception as exc:
        return None, None, ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            "Frozen index file integrity verification failed",
            details={"reason_code": "frozen_index_mismatch"},
        )

    # 4. Acquire durable pin owned by this request
    pin_id = repository.pin_generation(
        generation_id=gen_id,
        pinned_for=str(request_id),
        pinned_by="GEN-02",
    )

    return gen_id, pin_id, None

