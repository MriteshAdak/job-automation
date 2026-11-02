"""Fetch controller facade and multi-source failure isolation (INGEST-01-S08).

Orchestrates ingestion across permitted sources, enforcing atomic preflight
selection, durable capture, and strict runtime failure isolation between
independent sources.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.manifests import finalize_manifest
from job_automation.ingestion.models import (
    ControllerOptions,
    FetchStageResult,
    SourceFetchResult,
)
from job_automation.ingestion.pagination import PaginationTraverser
from job_automation.ingestion.ports import (
    AdapterRegistry,
    ClockProtocol,
    SleeperProtocol,
    SystemClock,
    SystemSleeper,
)
from job_automation.ingestion.request_control import DomainRateLimiter
from job_automation.sources.models import EffectiveSource, SourceSelectionResult
from job_automation.sources.service import SourceRegistryService
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class FetchController:
    """Central service orchestrating ingestion for a pipeline run."""

    def __init__(
        self,
        storage: StorageEngine,
        registry_service: SourceRegistryService | None = None,
        options: ControllerOptions | None = None,
        adapter_registry: AdapterRegistry | None = None,
        clock: ClockProtocol | None = None,
        sleeper: SleeperProtocol | None = None,
    ) -> None:
        self.storage = storage
        self.registry_service = registry_service
        self.options = options or ControllerOptions()
        self.adapter_registry = adapter_registry or AdapterRegistry()
        self.clock = clock or SystemClock()
        self.sleeper = sleeper or SystemSleeper()

        # Shared resources
        self.sink = DurableRawCaptureSink(self.storage.raw_dir)
        self.rate_limiter = DomainRateLimiter()
        self.cache = PageCache(
            raw_dir=self.storage.raw_dir,
            ttl_seconds=self.options.cache_ttl_seconds if self.options.cache_mode == "ttl" else 0,
        )

    def fetch_source(
        self,
        run_id: uuid.UUID,
        effective_source: EffectiveSource,
        resume: bool = True,
    ) -> SourceFetchResult:
        """Execute ingestion for a single checked effective source."""
        adapter = self.adapter_registry.create_adapter(
            effective_source, self.sink, self.options
        )
        traverser = PaginationTraverser(
            run_id=run_id,
            effective_source=effective_source,
            adapter=adapter,
            storage=self.storage,
            sink=self.sink,
            options=self.options,
            clock=self.clock,
            sleeper=self.sleeper,
            rate_limiter=self.rate_limiter,
            cache=self.cache,
        )
        return traverser.traverse(resume=resume)

    def run_fetch(
        self,
        run_id: uuid.UUID,
        source_keys: Sequence[str] | None = None,
        resume: bool = True,
    ) -> FetchStageResult:
        """Execute ingestion across requested sources.

        Enforces atomic preflight selection: if any requested source is invalid,
        blocked, or missing, no sources are executed.

        Enforces runtime isolation: once execution starts, a failure in one
        source never rolls back or erases the results of another source.
        """
        if self.registry_service is None:
            raise ValueError("SourceRegistryService must be configured to run multi-source fetch")

        # 1. Atomic preflight selection
        selection: SourceSelectionResult
        if source_keys is not None:
            selection = self.registry_service.select_sources(source_keys)
        else:
            # Select all configured and enabled sources
            all_keys = [
                s.config.source_key
                for s in self.registry_service.sources.values()
                if s.config.enabled
            ]
            selection = self.registry_service.select_sources(all_keys)

        if not selection.is_valid:
            msg = f"Atomic preflight rejected selection: {selection.blockers}"
            logger.error(msg)
            raise ValueError(msg)

        stage_result = FetchStageResult(run_id=run_id)

        # 2. Sequential isolated execution
        for eff_source in selection.selected_sources:
            src_key = eff_source.config.source_key
            stage_result.sources_attempted += 1

            try:
                src_res = self.fetch_source(run_id, eff_source, resume=resume)
            except Exception as exc:
                # Catch unexpected adapter or source runtime exceptions and isolate them
                logger.exception("Unexpected exception executing source '%s'", src_key)
                err = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message=f"Source execution failed with {type(exc).__name__}: {exc}",
                    details={"code": "source_fatal_exception", "source_key": src_key},
                )
                now = self.clock.now_utc()
                scope_id = f"{eff_source.config.provider}_{eff_source.config.board_id}"
                failed_manifest = FetchManifest(
                    run_id=run_id,
                    source_key=src_key,
                    scope_id=scope_id,
                    start_time=now,
                    end_time=now,
                    cursor_in=None,
                    cursor_out=None,
                    page_count=0,
                    raw_response_refs=[],
                    observed_posting_identities=[],
                    outcome=FetchOutcome.FAILED,
                    inventory_semantics=eff_source.config.inventory_semantics,
                    error=err,
                )
                finalized = finalize_manifest(self.storage, failed_manifest)
                src_res = SourceFetchResult(
                    source_key=src_key,
                    outcome=FetchOutcome.FAILED,
                    manifest=finalized,
                    page_count=0,
                    observed_identities_count=0,
                    raw_records_count=0,
                    accepted_drafts_count=0,
                    rejected_records_count=0,
                    warnings_count=0,
                    requests_made=0,
                    from_cache_count=0,
                    error=err,
                    receipts=[],
                )

            # Record outcome counters
            if src_res.outcome == FetchOutcome.COMPLETE:
                stage_result.sources_completed += 1
            elif src_res.outcome == FetchOutcome.PARTIAL:
                stage_result.sources_partial += 1
            else:
                stage_result.sources_failed += 1

            stage_result.total_requests += src_res.requests_made
            stage_result.total_pages += src_res.page_count
            stage_result.total_raw_observations += src_res.raw_records_count
            stage_result.total_unique_identities += src_res.observed_identities_count
            stage_result.source_results[src_key] = src_res

        return stage_result
