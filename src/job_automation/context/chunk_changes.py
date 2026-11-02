"""Manifest comparison and invalidation tracking for CONTEXT-02 evidence chunks."""

from __future__ import annotations

import uuid

from job_automation.context.chunk_errors import ChunkValidationError
from job_automation.contracts.evidence_chunks import (
    BindingTransition,
    ChunkChangeSet,
    ChunkSet,
)


def compare_chunk_manifests(
    base_manifest: ChunkSet | None,
    target_manifest: ChunkSet,
) -> ChunkChangeSet:
    """Compare base and target manifests to produce deterministic invalidation reports."""
    # 1. Initial build: no base manifest
    if base_manifest is None:
        added_chunk_ids = [c.chunk_id for c in target_manifest.chunks]
        transitions = [
            BindingTransition(
                chunk_id=c.chunk_id,
                old_binding=None,
                new_binding=c.binding_fingerprint,
                reason_code="added",
            )
            for c in target_manifest.chunks
        ]
        return ChunkChangeSet(
            candidate_id=target_manifest.candidate_id,
            purpose=target_manifest.purpose,
            base_manifest_fingerprint=None,
            target_manifest_fingerprint=target_manifest.manifest_fingerprint,
            added_chunk_ids=added_chunk_ids,
            binding_transitions=transitions,
            reasons=["initial_manifest_build"],
            replacement_required=bool(added_chunk_ids),
        )

    # 2. Scope match validation
    if base_manifest.candidate_id != target_manifest.candidate_id:
        raise ChunkValidationError(
            f"Cannot compare manifests across different candidates: base='{base_manifest.candidate_id}', target='{target_manifest.candidate_id}'",
            field_path="candidate_id",
        )
    if base_manifest.purpose != target_manifest.purpose:
        raise ChunkValidationError(
            f"Cannot compare manifests across different purposes: base='{base_manifest.purpose}', target='{target_manifest.purpose}'",
            field_path="purpose",
        )

    # 3. Index base and target chunks by chunk_id
    base_map = {c.chunk_id: c for c in base_manifest.chunks}
    target_map = {c.chunk_id: c for c in target_manifest.chunks}

    added_chunk_ids = [cid for cid in target_map if cid not in base_map]
    removed_chunk_ids = [cid for cid in base_map if cid not in target_map]

    content_changed_chunk_ids: list[uuid.UUID] = []
    rebound_unchanged_chunk_ids: list[uuid.UUID] = []
    transitions: list[BindingTransition] = []
    reasons: list[str] = []

    for cid in added_chunk_ids:
        transitions.append(
            BindingTransition(
                chunk_id=cid,
                old_binding=None,
                new_binding=target_map[cid].binding_fingerprint,
                reason_code="added",
            )
        )

    for cid in removed_chunk_ids:
        transitions.append(
            BindingTransition(
                chunk_id=cid,
                old_binding=base_map[cid].binding_fingerprint,
                new_binding=None,
                reason_code="removed_tombstone",
            )
        )

    for cid, target_chunk in target_map.items():
        if cid in base_map:
            base_chunk = base_map[cid]
            if target_chunk.chunk_version != base_chunk.chunk_version:
                content_changed_chunk_ids.append(cid)
                if target_chunk.parent_id != base_chunk.parent_id:
                    reason = "reparented"
                else:
                    reason = "content_updated"
                transitions.append(
                    BindingTransition(
                        chunk_id=cid,
                        old_binding=base_chunk.binding_fingerprint,
                        new_binding=target_chunk.binding_fingerprint,
                        reason_code=reason,
                    )
                )
            else:
                # Content identical; check if binding changed (e.g. profile_version bumped)
                if target_chunk.binding_fingerprint != base_chunk.binding_fingerprint:
                    rebound_unchanged_chunk_ids.append(cid)
                    transitions.append(
                        BindingTransition(
                            chunk_id=cid,
                            old_binding=base_chunk.binding_fingerprint,
                            new_binding=target_chunk.binding_fingerprint,
                            reason_code="rebound_snapshot",
                        )
                    )

    settings_changed = base_manifest.settings_fingerprint != target_manifest.settings_fingerprint
    if settings_changed:
        reasons.append("chunking_settings_changed")

    if added_chunk_ids:
        reasons.append(f"added_{len(added_chunk_ids)}_chunks")
    if removed_chunk_ids:
        reasons.append(f"removed_{len(removed_chunk_ids)}_chunks")
    if content_changed_chunk_ids:
        reasons.append(f"content_updated_{len(content_changed_chunk_ids)}_chunks")
    if rebound_unchanged_chunk_ids:
        reasons.append(f"rebound_{len(rebound_unchanged_chunk_ids)}_chunks")

    if not reasons:
        reasons.append("identical_manifest")

    replacement_required = bool(
        added_chunk_ids or removed_chunk_ids or content_changed_chunk_ids or settings_changed
    )

    return ChunkChangeSet(
        candidate_id=target_manifest.candidate_id,
        purpose=target_manifest.purpose,
        base_manifest_fingerprint=base_manifest.manifest_fingerprint,
        target_manifest_fingerprint=target_manifest.manifest_fingerprint,
        added_chunk_ids=added_chunk_ids,
        removed_chunk_ids=removed_chunk_ids,
        content_changed_chunk_ids=content_changed_chunk_ids,
        rebound_unchanged_chunk_ids=rebound_unchanged_chunk_ids,
        binding_transitions=transitions,
        reasons=reasons,
        replacement_required=replacement_required,
    )

