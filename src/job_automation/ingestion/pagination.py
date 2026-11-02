"""Bounded pagination traversal, cycle detection, and checkpoint advancement (INGEST-01-S05).

Executes ordered page retrieval, handles retries, bounds request and page counts,
enforces inter-request spacing, and ensures interrupted traversals are never
marked complete.
"""

from __future__ import annotations

import logging
import uuid
from typing import Sequence

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Adapter
from job_automation.contracts.postings import FetchManifest, RawPosting
from job_automation.ingestion.cache import PageCache
from job_automation.ingestion.execution import PageExecutionResult, PageExecutor
from job_automation.ingestion.manifests import build_fetch_manifest, finalize_manifest
from job_automation.ingestion.models import (
    ControllerOptions,
    PageReceipt,
    SourceCheckpoint,
    SourceFetchResult,
)
from job_automation.ingestion.persistence import PagePersistenceManager
from job_automation.ingestion.ports import ClockProtocol, SleeperProtocol
from job_automation.ingestion.request_control import DomainRateLimiter, RequestBudget
from job_automation.ingestion.retry import compute_backoff_delay, extract_retry_after, is_recoverable_error
from job_automation.sources.adapters.raw import RawCaptureSink
from job_automation.sources.models import EffectiveSource
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class PaginationTraverser:
    """Manages pagination traversal for a single effective source."""

    def __init__(
        self,
        run_id: uuid.UUID,
        effective_source: EffectiveSource,
        adapter: Adapter,
        storage: StorageEngine,
        sink: RawCaptureSink,
        options: ControllerOptions,
        clock: ClockProtocol,
        sleeper: SleeperProtocol,
        rate_limiter: DomainRateLimiter,
        cache: PageCache,
    ) -> None:
        self.run_id = run_id
        self.effective_source = effective_source
        self.adapter = adapter
        self.storage = storage
        self.sink = sink
        self.options = options
        self.clock = clock
        self.sleeper = sleeper
        self.rate_limiter = rate_limiter
        self.cache = cache

        self.config = effective_source.config
        self.source_key = self.config.source_key
        self.scope_id = f"{self.config.provider}_{self.config.board_id}"
        self.domain_key = self.config.provider

        self.persistence = PagePersistenceManager(storage)
        self.executor = PageExecutor(effective_source, adapter)

    def traverse(self, resume: bool = True) -> SourceFetchResult:
        """Execute bounded traversal for this source and return SourceFetchResult."""
        start_time = self.clock.now_utc()
        start_mono = self.clock.monotonic()

        budget = RequestBudget.from_source_and_options(
            self.effective_source, self.options, start_mono
        )

        traversal_id = f"{self.run_id}_{self.source_key}_{uuid.uuid4().hex[:8]}"

        # Check for existing checkpoint if resume enabled
        checkpoint: SourceCheckpoint | None = None
        if resume:
            checkpoint = self.persistence.load_checkpoint(
                self.run_id, self.source_key, self.scope_id
            )

        cursor_in: Continuation | None = None
        current_continuation: Continuation | None = None
        visited_tokens: list[str] = []
        is_resumed_without_prefix = False

        prior_observed: list[str] = []
        prior_refs: list[str] = []
        prior_page_count = 0

        if checkpoint is not None:
            traversal_id = checkpoint.traversal_id
            current_continuation = checkpoint.current_continuation
            cursor_in = checkpoint.initial_cursor_in
            visited_tokens = list(checkpoint.visited_tokens)
            prior_observed = list(checkpoint.records_observed)
            prior_refs = list(checkpoint.raw_response_refs)
            prior_page_count = checkpoint.pages_completed
            if checkpoint.pages_completed == 0 and current_continuation is not None:
                is_resumed_without_prefix = True
        else:
            cursor_in = current_continuation
            checkpoint = SourceCheckpoint(
                traversal_id=traversal_id,
                run_id=self.run_id,
                source_key=self.source_key,
                scope_id=self.scope_id,
                adapter_name=getattr(self.adapter, "ADAPTER_NAME", self.config.provider),
                initial_cursor_in=cursor_in,
                current_continuation=None,
                visited_tokens=[],
                pages_completed=0,
                records_observed=[],
                raw_response_refs=[],
                requests_made=0,
                created_at=start_time,
                updated_at=start_time,
            )

        receipts: list[PageReceipt] = []
        requests_made = 0
        from_cache_count = 0
        stopped_by_limit = False
        stopped_by_error: ClassifiedError | None = None
        used_cache = False

        page_index = checkpoint.pages_completed

        while True:
            # 1. Check page budget
            if not budget.has_pages():
                stopped_by_limit = True
                logger.info("Source '%s' reached page cap (%d)", self.source_key, budget.max_pages)
                break

            # 2. Check source deadline
            if budget.is_deadline_exceeded(self.clock.monotonic()):
                stopped_by_limit = True
                logger.warning("Source '%s' exceeded time deadline", self.source_key)
                break

            page_index += 1
            cont_token_str = current_continuation.encode() if current_continuation else None

            # 3. Check cycle
            if cont_token_str is not None:
                if cont_token_str in visited_tokens:
                    stopped_by_error = ClassifiedError.from_category(
                        category=ErrorCategory.VALIDATION,
                        message=f"Pagination cycle detected for continuation token: '{cont_token_str[:32]}...'",
                        details={"code": "pagination_cycle", "source_key": self.source_key},
                    )
                    break
                visited_tokens.append(cont_token_str)

            # 4. Try cache if enabled
            cache_hit = False
            cached_page = None
            cached_drafts = None

            if self.cache.is_enabled:
                cache_key = self.cache.compute_cache_key(
                    source_key=self.source_key,
                    scope_id=self.scope_id,
                    adapter_name=checkpoint.adapter_name,
                    continuation_token_str=cont_token_str,
                )
                hit_data = self.cache.get(cache_key, self.clock.now_utc(), self.sink)
                if hit_data is not None:
                    cached_page, cached_drafts = hit_data
                    cache_hit = True
                    from_cache_count += 1
                    used_cache = True

            exec_res: PageExecutionResult

            if cache_hit and cached_page is not None and cached_drafts is not None:
                # Cache hit: 0 network requests
                budget.consume_page()
                exec_res = PageExecutionResult(
                    page=cached_page,
                    draft_results=cached_drafts,
                    all_issues=list(cached_page.issues),
                    raw_records=list(cached_page.items),
                    observed_posting_ids=[item.source_key.source_posting_id for item in cached_page.items],
                    parent_refs=list(cached_page.raw_response_refs),
                )
                attempt_count = 1
            else:
                # 5. Network fetch with spacing and retries
                if not budget.has_requests():
                    stopped_by_limit = True
                    break

                spacing = self.options.request_spacing_seconds
                if (
                    self.effective_source.request_policy
                    and self.effective_source.request_policy.request_spacing_seconds is not None
                ):
                    spacing = max(
                        spacing, self.effective_source.request_policy.request_spacing_seconds
                    )

                page_success = False
                attempt = 0
                max_attempts = self.options.max_attempts_per_page
                last_error: ClassifiedError | None = None

                while attempt < max_attempts:
                    if not budget.has_requests() or budget.is_deadline_exceeded(self.clock.monotonic()):
                        stopped_by_limit = True
                        break

                    attempt += 1
                    requests_made += 1
                    budget.consume_request()

                    # Enforce spacing between requests
                    self.rate_limiter.enforce_spacing(
                        self.domain_key, spacing, self.clock, self.sleeper
                    )

                    exec_res = self.executor.execute_page(continuation=current_continuation)

                    if exec_res.page.page_error is not None:
                        last_error = exec_res.page.page_error
                        if is_recoverable_error(last_error) and attempt < max_attempts:
                            retry_after = extract_retry_after(last_error, self.clock.now_utc())
                            delay = compute_backoff_delay(
                                attempt,
                                self.options.backoff_factor,
                                self.options.backoff_max_seconds,
                                retry_after_seconds=retry_after,
                            )
                            # If delay exceeds remaining deadline, stop rather than waiting past deadline
                            if delay > budget.remaining_deadline(self.clock.monotonic()):
                                stopped_by_limit = True
                                break
                            self.sleeper.sleep(delay)
                            continue
                        # Non-recoverable or attempts exhausted
                        break

                    # Page succeeded
                    page_success = True
                    budget.consume_page()
                    break

                attempt_count = attempt

                if not page_success and last_error is not None:
                    # Page fetch failed after attempts
                    stopped_by_error = last_error

                # If page succeeded and cache enabled, store in cache
                if page_success and self.cache.is_enabled and exec_res.page.page_error is None:
                    cache_key = self.cache.compute_cache_key(
                        source_key=self.source_key,
                        scope_id=self.scope_id,
                        adapter_name=checkpoint.adapter_name,
                        continuation_token_str=cont_token_str,
                    )
                    parent_hashes = [
                        r.raw_content_hash for r in exec_res.raw_records
                    ]
                    self.cache.put(
                        cache_key=cache_key,
                        source_key=self.source_key,
                        scope_id=self.scope_id,
                        adapter_name=checkpoint.adapter_name,
                        continuation_token=cont_token_str,
                        raw_response_refs=exec_res.parent_refs,
                        raw_response_hashes=parent_hashes,
                        page=exec_res.page,
                        draft_results=exec_res.draft_results,
                        now_utc=self.clock.now_utc(),
                    )

            # Build receipt
            page = exec_res.page
            receipt = PageReceipt(
                traversal_id=traversal_id,
                page_index=page_index,
                attempt_count=attempt_count,
                continuation_in=page.continuation_in,
                continuation_out=page.continuation_out,
                source_key=self.source_key,
                scope_id=self.scope_id,
                adapter_name=checkpoint.adapter_name,
                raw_response_refs=list(page.raw_response_refs),
                raw_response_hashes=[r.raw_content_hash for r in exec_res.raw_records],
                observed_posting_ids=exec_res.observed_posting_ids,
                raw_record_refs=[r.raw_payload_ref for r in exec_res.raw_records],
                draft_results=exec_res.draft_results,
                issues=exec_res.all_issues,
                from_cache=cache_hit,
                fetch_time=self.clock.now_utc(),
                exhausted=page.exhausted,
                truncated=page.truncated,
                page_error=page.page_error,
            )
            receipts.append(receipt)

            # Update checkpoint state
            checkpoint.pages_completed = len(receipts)
            checkpoint.current_continuation = page.continuation_out
            checkpoint.visited_tokens = visited_tokens
            checkpoint.requests_made = requests_made
            checkpoint.updated_at = self.clock.now_utc()

            for pid in exec_res.observed_posting_ids:
                if pid not in checkpoint.records_observed:
                    checkpoint.records_observed.append(pid)
            for ref in page.raw_response_refs:
                if ref not in checkpoint.raw_response_refs:
                    checkpoint.raw_response_refs.append(ref)

            # Commit page and checkpoint atomically
            self.persistence.commit_page(receipt, checkpoint, exec_res.raw_records)

            # Check termination conditions
            if page.page_error is not None:
                stopped_by_error = page.page_error
                break

            if page.exhausted:
                # Source signaled terminal exhaustion
                break

            if page.truncated:
                stopped_by_limit = True
                break

            if page.continuation_out is None and not page.exhausted:
                # Contract error: neither exhausted nor has continuation_out
                stopped_by_error = ClassifiedError.from_category(
                    category=ErrorCategory.VALIDATION,
                    message="Adapter returned non-exhausted page without continuation_out",
                    details={"code": "missing_continuation", "source_key": self.source_key},
                )
                break

            current_continuation = page.continuation_out

        end_time = self.clock.now_utc()

        # Build and finalize C04 manifest
        manifest = build_fetch_manifest(
            run_id=self.run_id,
            effective_source=self.effective_source,
            start_time=start_time,
            end_time=end_time,
            cursor_in=cursor_in,
            cursor_out=current_continuation,
            receipts=receipts,
            prior_observed_identities=prior_observed,
            prior_raw_refs=prior_refs,
            prior_page_count=prior_page_count,
            stopped_by_limit=stopped_by_limit,
            stopped_by_error=stopped_by_error,
            used_cache=used_cache,
            is_resumed_without_prefix=is_resumed_without_prefix,
        )

        finalized = finalize_manifest(self.storage, manifest)

        # Aggregate counts
        raw_count = sum(len(r.raw_record_refs) for r in receipts)
        accepted_count = sum(
            1 for r in receipts for d in r.draft_results if d.draft is not None
        )
        rejected_count = sum(
            1 for r in receipts for d in r.draft_results if d.draft is None
        )
        warning_count = sum(
            1 for r in receipts for issue in r.issues if issue.severity == "warning"
        )

        return SourceFetchResult(
            source_key=self.source_key,
            outcome=finalized.outcome,
            manifest=finalized,
            page_count=len(receipts),
            observed_identities_count=len(finalized.observed_posting_identities),
            raw_records_count=raw_count,
            accepted_drafts_count=accepted_count,
            rejected_records_count=rejected_count,
            warnings_count=warning_count,
            requests_made=requests_made,
            from_cache_count=from_cache_count,
            error=finalized.error,
            receipts=receipts,
        )
