"""Default configuration and validation helpers for local vector and keyword indexing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_automation.contracts.retrieval_index import IndexSettings

DEFAULT_INDEX_SETTINGS = IndexSettings(
    schema_version="1.0",
    index_version="v1",
    algorithm_version="v1",
    format_version="v1",
    canonicalization_version="v1",
    dtype="float32",
    byte_order="little_endian",
    metric="cosine",
    normalization="l2",
    analyzer_version="v1",
    analyzer_options={"lowercase": True, "preserve_skills": True},
    max_chunks=10000,
    max_dimension=4096,
    max_text_bytes=65536,
    max_build_memory_bytes=1073741824,  # 1 GB
    max_disk_bytes=10737418240,  # 10 GB
    max_build_time_seconds=300.0,
    cleanup_retained_generations=2,
)


def load_index_settings(settings_path: str | Path | None = None) -> IndexSettings:
    """Load and validate IndexSettings from a JSON file, or return defaults."""
    if settings_path is None:
        return DEFAULT_INDEX_SETTINGS

    p = Path(settings_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Index settings file not found: {p}")

    import json

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    return IndexSettings.model_validate(data)

