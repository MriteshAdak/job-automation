"""Revision creation, projection, and deterministic current revision selection."""

from __future__ import annotations

import uuid
from datetime import datetime

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import PostingRevision
from job_automation.contracts.postings import NormalizedPosting


def create_posting_revision(
    canonical_job_id: uuid.UUID,
    normalized: NormalizedPosting,
    content_hash: str,
) -> PostingRevision:
    """Instantiate a new immutable PostingRevision snapshot."""
    app_urls = [normalized.application_url] if normalized.application_url else []
    return PostingRevision(
        revision_id=uuid.uuid4(),
        canonical_job_id=canonical_job_id,
        source_key=normalized.source_key,
        content_hash=content_hash,
        title=normalized.title.strip(),
        first_seen_at=normalized.observed_at,
        last_seen_at=normalized.observed_at,
        source_urls=[normalized.source_url],
        application_urls=app_urls,
        availability=PostingAvailability.ACTIVE,
    )


def update_revision_observation(
    revision: PostingRevision,
    observed_at: datetime,
    source_url: str,
    application_url: str | None = None,
) -> PostingRevision:
    """Advance observation metadata without mutating historical content."""
    # Ensure source URLs list contains the observed source URL
    src_urls = list(revision.source_urls)
    if source_url and source_url not in src_urls:
        src_urls.append(source_url)

    # Ensure application URLs list contains the observed application URL
    app_urls = list(revision.application_urls)
    if application_url and application_url not in app_urls:
        app_urls.append(application_url)

    new_last_seen = max(revision.last_seen_at, observed_at)
    new_first_seen = min(revision.first_seen_at, observed_at)

    return revision.model_copy(
        update={
            "first_seen_at": new_first_seen,
            "last_seen_at": new_last_seen,
            "source_urls": src_urls,
            "application_urls": app_urls,
        }
    )


def select_current_revision(revisions: list[PostingRevision]) -> uuid.UUID:
    """Deterministically select active revision ID from list.

    Rule: latest last_seen_at with stable tie-break on source key tuple and revision ID.
    """
    if not revisions:
        raise ValueError("Cannot select current revision from empty revision list")

    sorted_revs = sorted(
        revisions,
        key=lambda r: (
            r.last_seen_at,
            r.first_seen_at,
            r.source_key.provider,
            r.source_key.board_id,
            r.source_key.source_posting_id,
            str(r.revision_id),
        ),
        reverse=True,
    )
    return sorted_revs[0].revision_id

