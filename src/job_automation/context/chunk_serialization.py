"""Deterministic serialization and round-trip deserialization for CONTEXT-02 chunk contracts."""

from __future__ import annotations

import json
from typing import Any

from job_automation.contracts.evidence_chunks import (
    ChunkChangeSet,
    ChunkSet,
    EvidenceChunk,
)


def serialize_chunk_to_json(chunk: EvidenceChunk) -> str:
    """Serialize EvidenceChunk to canonical UTF-8 JSON with sorted keys."""
    data = chunk.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def serialize_chunk_set_to_json(chunk_set: ChunkSet) -> str:
    """Serialize ChunkSet manifest to canonical UTF-8 JSON with sorted keys."""
    data = chunk_set.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def serialize_chunk_change_set_to_json(change_set: ChunkChangeSet) -> str:
    """Serialize ChunkChangeSet to canonical UTF-8 JSON with sorted keys."""
    data = change_set.model_dump(mode="json")
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False)


def deserialize_chunk_set_from_json(json_str: str) -> ChunkSet:
    """Parse JSON string into validated ChunkSet instance."""
    data = json.loads(json_str)
    return ChunkSet.model_validate(data)


def deserialize_chunk_change_set_from_json(json_str: str) -> ChunkChangeSet:
    """Parse JSON string into validated ChunkChangeSet instance."""
    data = json.loads(json_str)
    return ChunkChangeSet.model_validate(data)

