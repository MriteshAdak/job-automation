"""Fake downstream index consumer for testing CONTEXT-02 chunking handoff."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.contracts.evidence_chunks import (
    ChunkChangeSet,
    ChunkSet,
    EvidenceChunk,
)


class FakeIndexConsumer:
    """Simulates a downstream vector/keyword index consumer receiving ChunkSets and ChangeSets."""

    def __init__(self) -> None:
        self.chunks: dict[uuid.UUID, EvidenceChunk] = {}
        self.active_manifest_fingerprint: str | None = None
        self.active_candidate_id: uuid.UUID | None = None
        self.active_profile_version: str | None = None
        self.active_purpose: str | None = None
        self.tombstones: list[uuid.UUID] = []

    def ingest_initial(self, manifest: ChunkSet) -> None:
        """Perform initial ingestion of a full ChunkSet manifest."""
        self.chunks.clear()
        for chunk in manifest.chunks:
            self.chunks[chunk.chunk_id] = chunk

        self.active_manifest_fingerprint = manifest.manifest_fingerprint
        self.active_candidate_id = manifest.candidate_id
        self.active_profile_version = manifest.profile_version
        self.active_purpose = manifest.purpose

    def apply_change_set(
        self, change_set: ChunkChangeSet, target_manifest: ChunkSet
    ) -> None:
        """Apply an invalidation change set atomically updating active index state."""
        target_map = {c.chunk_id: c for c in target_manifest.chunks}

        # 1. Remove tombstones
        for removed_id in change_set.removed_chunk_ids:
            self.chunks.pop(removed_id, None)
            self.tombstones.append(removed_id)

        # 2. Add or update changed chunks
        for added_id in change_set.added_chunk_ids:
            if added_id in target_map:
                self.chunks[added_id] = target_map[added_id]

        for changed_id in change_set.content_changed_chunk_ids:
            if changed_id in target_map:
                self.chunks[changed_id] = target_map[changed_id]

        for rebound_id in change_set.rebound_unchanged_chunk_ids:
            if rebound_id in target_map:
                self.chunks[rebound_id] = target_map[rebound_id]

        self.active_manifest_fingerprint = target_manifest.manifest_fingerprint
        self.active_candidate_id = target_manifest.candidate_id
        self.active_profile_version = target_manifest.profile_version
        self.active_purpose = target_manifest.purpose

    def get_chunk(self, chunk_id: uuid.UUID) -> EvidenceChunk | None:
        """Query active chunk by ID."""
        return self.chunks.get(chunk_id)

    def list_chunk_ids(self) -> list[uuid.UUID]:
        """List all active chunk UUIDs."""
        return list(self.chunks.keys())

    def verify_active_binding(
        self,
        expected_candidate_id: uuid.UUID,
        expected_profile_version: str,
        expected_purpose: str,
    ) -> bool:
        """Verify that the consumer's active state satisfies exact expected bindings."""
        if self.active_candidate_id != expected_candidate_id:
            return False
        if self.active_profile_version != expected_profile_version:
            return False
        if self.active_purpose != expected_purpose:
            return False
        return True

