"""Deterministic serialization helpers for index manifests and chunk exports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from job_automation.contracts.evidence_chunks import EvidenceChunk
from job_automation.contracts.retrieval_index import IndexManifest


def to_canonical_json(data: Any) -> str:
    """Serialize model or dictionary to sorted-key, unescaped UTF-8 canonical JSON."""
    if hasattr(data, "model_dump"):
        dumped = data.model_dump(mode="json")
    else:
        dumped = data
    return json.dumps(dumped, sort_keys=True, indent=2, ensure_ascii=False)


def write_manifest_file(manifest: IndexManifest, dest_path: Path) -> None:
    """Write IndexManifest to file in canonical formatted JSON."""
    content = to_canonical_json(manifest)
    dest_path.write_text(content, encoding="utf-8")


def read_manifest_file(source_path: Path) -> IndexManifest:
    """Read and validate IndexManifest from file."""
    content = source_path.read_text(encoding="utf-8")
    return IndexManifest.model_validate_json(content)


def write_chunks_file(chunks: list[EvidenceChunk], dest_path: Path) -> None:
    """Write list of EvidenceChunk to file in canonical JSON."""
    content = to_canonical_json([c.model_dump(mode="json") for c in chunks])
    dest_path.write_text(content, encoding="utf-8")


def read_chunks_file(source_path: Path) -> list[EvidenceChunk]:
    """Read and parse list of EvidenceChunk from file."""
    content = source_path.read_text(encoding="utf-8")
    data = json.loads(content)
    return [EvidenceChunk.model_validate(item) for item in data]

