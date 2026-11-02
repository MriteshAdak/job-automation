"""Tests for canonical availability aggregation across multiple linked sources (IDENTITY-02-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.aggregate import aggregate_canonical_availability
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestMultiSource:
    def test_canonical_truth_table_aggregation(self) -> None:
        now = datetime.now(timezone.utc)
        sk_a = SourceKey(provider="gh", board_id="acme", source_posting_id="1")
        sk_b = SourceKey(provider="an", board_id="de", source_posting_id="2")

        # 1. Unavailable + Active -> ACTIVE
        s_unavail = SourcePostingAvailability(
            source_key=sk_a,
            scope_id="sc_a",
            availability=PostingAvailability.UNAVAILABLE,
            first_seen_at=now,
            last_seen_at=now,
        )
        s_active = SourcePostingAvailability(
            source_key=sk_b,
            scope_id="sc_b",
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now,
            last_seen_at=now,
        )
        avail1, r1 = aggregate_canonical_availability([s_unavail, s_active])
        assert avail1 == PostingAvailability.ACTIVE
        assert "linked_source_active" in r1

        # 2. Unavailable + Not_Seen -> NOT_SEEN
        s_not_seen = SourcePostingAvailability(
            source_key=sk_b,
            scope_id="sc_b",
            availability=PostingAvailability.NOT_SEEN,
            first_seen_at=now,
            last_seen_at=now,
        )
        avail2, r2 = aggregate_canonical_availability([s_unavail, s_not_seen])
        assert avail2 == PostingAvailability.NOT_SEEN
        assert "linked_source_not_seen" in r2

        # 3. Unavailable + Unknown -> UNKNOWN
        s_unknown = SourcePostingAvailability(
            source_key=sk_b,
            scope_id="sc_b",
            availability=PostingAvailability.UNKNOWN,
            first_seen_at=now,
            last_seen_at=now,
        )
        avail3, r3 = aggregate_canonical_availability([s_unavail, s_unknown])
        assert avail3 == PostingAvailability.UNKNOWN
        assert "linked_source_unknown" in r3

        # 4. Unavailable + Unavailable -> UNAVAILABLE
        s_unavail_b = SourcePostingAvailability(
            source_key=sk_b,
            scope_id="sc_b",
            availability=PostingAvailability.UNAVAILABLE,
            first_seen_at=now,
            last_seen_at=now,
        )
        avail4, r4 = aggregate_canonical_availability([s_unavail, s_unavail_b])
        assert avail4 == PostingAvailability.UNAVAILABLE
        assert "all_linked_sources_unavailable" in r4

        # 5. Empty source list -> UNKNOWN
        avail5, r5 = aggregate_canonical_availability([])
        assert avail5 == PostingAvailability.UNKNOWN

    def test_end_to_end_multi_source_canonical_preservation(self, tmp_path) -> None:
        db_path = tmp_path / "multi_e2e.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        now = datetime.now(timezone.utc)
        cid = uuid.uuid4()
        rev_id = uuid.uuid4()
        sk_primary = SourceKey(provider="gh", board_id="acme", source_posting_id="100")
        sk_secondary = SourceKey(provider="an", board_id="de", source_posting_id="200")

        # Create CanonicalJob with two linked sources
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=cid,
            source_key=sk_primary,
            content_hash="sha256:" + "a" * 64,
            title="Senior Engineer",
            first_seen_at=now,
            last_seen_at=now,
            availability=PostingAvailability.ACTIVE,
        )
        job = CanonicalJob(
            canonical_job_id=cid,
            company_name="Acme Corp",
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk_primary, sk_secondary],
            revisions=[rev],
        )
        storage.canonical_jobs.save_canonical_job(job)

        # Map both source keys to this canonical job in source_identities
        storage.identity.save_source_identity(sk_primary, cid, now, now)
        storage.identity.save_source_identity(sk_secondary, cid, now, now)

        # Primary source is UNAVAILABLE
        storage.availability.save_source_availability(
            SourcePostingAvailability(
                source_key=sk_primary,
                scope_id="gh_acme",
                canonical_job_id=cid,
                availability=PostingAvailability.UNAVAILABLE,
                first_seen_at=now,
                last_seen_at=now,
                miss_count=3,
            )
        )

        # Secondary source is ACTIVE
        storage.availability.save_source_availability(
            SourcePostingAvailability(
                source_key=sk_secondary,
                scope_id="an_de",
                canonical_job_id=cid,
                availability=PostingAvailability.ACTIVE,
                first_seen_at=now,
                last_seen_at=now,
                miss_count=0,
            )
        )

        # Recompute canonical availability
        change = service.recompute_canonical_availability(cid)

        # Because secondary source is ACTIVE, canonical job MUST remain ACTIVE!
        saved_job = storage.canonical_jobs.get_canonical_job(cid)
        assert saved_job is not None
        assert saved_job.availability == PostingAvailability.ACTIVE

