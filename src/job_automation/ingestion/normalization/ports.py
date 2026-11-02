"""Normalization ports, protocols, and options (INGEST-02).

Defines the RawProvenanceReader protocol, in-memory reader implementations,
and normalizer configuration options.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash


@runtime_checkable
class RawProvenanceReader(Protocol):
    """Protocol for resolving an immutable raw reference to bytes and trusted content hash."""

    def get_raw(self, raw_reference: str) -> tuple[bytes, str] | None:
        """Resolve a raw reference to (raw_bytes, raw_content_hash).

        Returns:
            (raw_bytes, raw_content_hash) if found, or None if unresolved.
        """
        ...


class InMemoryRawProvenanceReader:
    """In-memory raw provenance reader for test isolation and offline processing."""

    def __init__(
        self,
        initial_entries: dict[str, bytes | tuple[bytes, str]] | None = None,
    ) -> None:
        self._entries: dict[str, tuple[bytes, str]] = {}
        if initial_entries:
            for ref, val in initial_entries.items():
                if isinstance(val, tuple):
                    self._entries[ref] = val
                else:
                    self._entries[ref] = (val, compute_content_hash(val))

    def register(self, raw_reference: str, content: bytes, content_hash: str | None = None) -> None:
        """Register raw bytes and optional content hash under a reference."""
        h = content_hash or compute_content_hash(content)
        self._entries[raw_reference] = (content, h)

    def get_raw(self, raw_reference: str) -> tuple[bytes, str] | None:
        return self._entries.get(raw_reference)


class CaptureSinkProvenanceReader:
    """Adapts any RawCaptureSink (in-memory or durable) into a RawProvenanceReader."""

    def __init__(self, sink: RawCaptureSink) -> None:
        self.sink = sink

    def get_raw(self, raw_reference: str) -> tuple[bytes, str] | None:
        payload_bytes = self.sink.get(raw_reference)
        if payload_bytes is None:
            return None
        return payload_bytes, compute_content_hash(payload_bytes)


class NormalizationOptions(ContractModel):
    """Configuration options for the normalizer."""

    normalizer_version: str = Field(
        default="1.0.0",
        min_length=1,
        description="Normalizer algorithm version fingerprint",
    )
    supported_mapping_versions: list[str] = Field(
        default_factory=lambda: ["1.0", "arbeitnow-1.0", "arbeitnow-map-v1"],
        description="List of supported source mapping versions",
    )
    default_timezone: str | None = Field(
        default=None,
        description="Optional IANA timezone name for naive datetimes if permitted",
    )
    strict_provenance: bool = Field(
        default=False,
        description="Whether to fail on missing field-level provenance",
    )
