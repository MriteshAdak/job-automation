"""Posting binding creation and lookup helpers (RUN-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.postings import NormalizedPosting
from job_automation.identity.hashing import compute_revision_content_hash
from job_automation.identity.models import IdentityResolutionResult
from job_automation.orchestration.records import PostingBinding
from job_automation.storage.engine import StorageEngine


def create_and_save_posting_binding(
    engine: StorageEngine,
    posting: NormalizedPosting,
    resolution: IdentityResolutionResult,
) -> PostingBinding:
    """Construct and persist an immutable PostingBinding from resolved identity."""
    norm_hash = compute_revision_content_hash(posting)
    binding = PostingBinding(
        canonical_job_id=resolution.canonical_job_id,
        revision_id=resolution.revision.revision_id,
        normalized_content_hash=norm_hash,
        raw_reference=posting.raw_reference,
        raw_content_hash=posting.raw_content_hash,
        source_key=posting.source_key,
        c06_snapshot=posting,
        mapper_version=posting.source_key.provider,
        normalizer_version=posting.normalizer_version,
    )
    engine.pipeline_work.save_posting_binding(binding)
    return binding

