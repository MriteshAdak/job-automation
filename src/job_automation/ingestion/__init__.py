"""Ingestion package public exports (INGEST-01, INGEST-02).

Exposes the FetchController facade, options, models, capture sink,
adapter registry, and normalizer service.
"""

from __future__ import annotations

from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.execution import PageExecutionResult, PageExecutor
from job_automation.ingestion.manifests import build_fetch_manifest, finalize_manifest
from job_automation.ingestion.models import (
    AttemptRecord,
    CacheEntry,
    ControllerOptions,
    FetchStageResult,
    PageReceipt,
    SourceCheckpoint,
    SourceFetchResult,
)
from job_automation.ingestion.normalization import (
    CaptureSinkProvenanceReader,
    DefaultNormalizer,
    InMemoryRawProvenanceReader,
    NormalizationOptions,
    NormalizationResult,
    QuarantineHandoff,
    RawProvenanceReader,
    build_quarantine_handoff,
)
from job_automation.ingestion.pagination import PaginationTraverser
from job_automation.ingestion.persistence import PagePersistenceManager
from job_automation.ingestion.ports import (
    AdapterFactory,
    AdapterRegistry,
    ClockProtocol,
    SleeperProtocol,
    SystemClock,
    SystemSleeper,
)
from job_automation.ingestion.request_control import DomainRateLimiter, RequestBudget
from job_automation.ingestion.retry import compute_backoff_delay, extract_retry_after, is_recoverable_error

__all__ = [
    "AdapterFactory",
    "AdapterRegistry",
    "AttemptRecord",
    "CacheEntry",
    "CaptureSinkProvenanceReader",
    "ClockProtocol",
    "ControllerOptions",
    "DefaultNormalizer",
    "DomainRateLimiter",
    "DurableRawCaptureSink",
    "FetchController",
    "FetchStageResult",
    "InMemoryRawProvenanceReader",
    "NormalizationOptions",
    "NormalizationResult",
    "PageCache",
    "PageExecutionResult",
    "PageExecutor",
    "PagePersistenceManager",
    "PageReceipt",
    "PaginationTraverser",
    "QuarantineHandoff",
    "RawProvenanceReader",
    "RequestBudget",
    "SleeperProtocol",
    "SourceCheckpoint",
    "SourceFetchResult",
    "SystemClock",
    "SystemSleeper",
    "build_fetch_manifest",
    "build_quarantine_handoff",
    "compute_backoff_delay",
    "extract_retry_after",
    "finalize_manifest",
    "is_recoverable_error",
]


