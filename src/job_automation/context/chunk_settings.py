"""Default settings and validation helpers for evidence chunking."""

from __future__ import annotations

from job_automation.contracts.evidence_chunks import ChunkingSettings

DEFAULT_CHUNKING_SETTINGS = ChunkingSettings(
    algorithm_version="v1",
    identity_scheme_version="v1",
    rendering_version="v1",
    parent_policy_version="v1",
    granularity="whole_fact",
    max_chunk_chars=None,
    strict_parents=False,
    size_unit="chars",
    overflow_behavior="error",
)

