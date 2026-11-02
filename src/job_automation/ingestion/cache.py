"""Safe page caching with content verification and TTL expiry (INGEST-01-S06).

Ensures cached pages avoid redundant network calls while maintaining exact
data integrity and preserving original observation timestamps.

CRITICAL INVARIANT: Reusing cached pages from a prior run cannot authorize
complete-board inventory claims; any traversal using cached pages produces a
PARTIAL C04 manifest.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from job_automation.contracts.adapter_results import AdapterPage, DraftResult
from job_automation.ingestion.models import CacheEntry
from job_automation.sources.adapters.raw import RawCaptureSink, verify_content_hash

logger = logging.getLogger(__name__)


class PageCache:
    """Manages persistent disk cache for fetched adapter pages."""

    def __init__(self, raw_dir: Path | str, ttl_seconds: int = 0) -> None:
        self.raw_dir = Path(raw_dir).resolve()
        self.ttl_seconds = ttl_seconds
        self.cache_dir = self.raw_dir / "cache"
        if self.ttl_seconds > 0:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_enabled(self) -> bool:
        return self.ttl_seconds > 0

    @staticmethod
    def compute_cache_key(
        source_key: str,
        scope_id: str,
        adapter_name: str,
        continuation_token_str: str | None,
        options_hash: str | None = None,
    ) -> str:
        """Compute deterministic SHA-256 cache key from request parameters."""
        raw_key = f"{source_key}|{scope_id}|{adapter_name}|{continuation_token_str or ''}|{options_hash or ''}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def get(
        self,
        cache_key: str,
        now_utc: datetime,
        sink: RawCaptureSink,
    ) -> tuple[AdapterPage, list[DraftResult]] | None:
        """Retrieve and verify a cached page. Returns None on miss or invalidation."""
        if not self.is_enabled:
            return None

        cache_file = self.cache_dir / f"{cache_key}.json"
        if not cache_file.is_file():
            return None

        try:
            content = cache_file.read_text(encoding="utf-8")
            entry = CacheEntry.model_validate_json(content)
        except Exception as exc:
            logger.warning("Corrupt cache entry '%s': %s", cache_key, exc)
            return None

        # Check TTL expiration
        if entry.expires_at <= now_utc:
            logger.debug("Cache entry '%s' expired at %s (now %s)", cache_key, entry.expires_at, now_utc)
            return None

        # Verify that all referenced raw payloads exist and match expected content hashes
        for ref, expected_hash in zip(entry.raw_response_refs, entry.raw_response_hashes):
            raw_bytes = sink.get(ref)
            if raw_bytes is None:
                logger.warning("Cache entry '%s' references missing payload '%s'", cache_key, ref)
                return None
            if not verify_content_hash(raw_bytes, expected_hash):
                logger.warning("Cache entry '%s' payload hash mismatch for '%s'", cache_key, ref)
                return None

        try:
            page = AdapterPage.model_validate_json(entry.adapter_page_json)
            drafts_data = json.loads(entry.draft_results_json)
            drafts = [DraftResult.model_validate(d) for d in drafts_data]
            return page, drafts
        except Exception as exc:
            logger.warning("Failed to deserialize cached contracts for '%s': %s", cache_key, exc)
            return None

    def put(
        self,
        cache_key: str,
        source_key: str,
        scope_id: str,
        adapter_name: str,
        continuation_token: str | None,
        raw_response_refs: Sequence[str],
        raw_response_hashes: Sequence[str],
        page: AdapterPage,
        draft_results: Sequence[DraftResult],
        now_utc: datetime,
    ) -> None:
        """Store a successful verified page in cache."""
        if not self.is_enabled:
            return

        # Never cache failed, error, or truncated pages
        if page.page_error is not None or page.truncated:
            return

        expires_at = now_utc + timedelta(seconds=self.ttl_seconds)
        entry = CacheEntry(
            cache_key=cache_key,
            source_key=source_key,
            scope_id=scope_id,
            adapter_name=adapter_name,
            continuation_token=continuation_token,
            raw_response_refs=list(raw_response_refs),
            raw_response_hashes=list(raw_response_hashes),
            adapter_page_json=page.model_dump_json(),
            draft_results_json=json.dumps([d.model_dump(mode="json") for d in draft_results]),
            captured_at=now_utc,
            expires_at=expires_at,
        )

        cache_file = self.cache_dir / f"{cache_key}.json"
        temp_file = self.cache_dir / f".tmp_{cache_key}.json"
        try:
            temp_file.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
            temp_file.replace(cache_file)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

