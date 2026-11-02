"""Tests for canonical availability recomputation across identity merge and reversal events (IDENTITY-02-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.identity.availability.service import AvailabilityService
from job_automation.identity.merges import execute_merge, execute_reversal
from job_automation.storage.engine import StorageEngine


class TestMembershipChanges:
    def test_merge_and_reversal_availability_recomputation(self, tmp_path) -> None:
        db_path = tmp_path / "merge_avail.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 20, 8, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 25, 8, 0, 0, tzinfo=timezone.utc)

        cid_a = uuid.uuid4()
        cid_b = uuid.uuid4()
        rev_a = uuid.uuid4()
        rev_b = uuid.uuid4()

        sk_a = SourceKey(provider="gh", board_id="a", source_posting_id="101")
        sk_b = SourceKey(provider="an", board_id="b", source_posting_id="202")

        # Job A: ACTIVE on Source A
        job_a = CanonicalJob(
            canonical_job_id=cid_a,
            company_name="Corp Alpha",
            current_revision_id=rev_a,
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk_a],
            revisions=[
                PostingRevision(
                    revision_id=rev_a,
                    canonical_job_id=cid_a,
                    source_key=sk_a,
                    content_hash="sha256:" + "a" * 64,
                    title="Engineer",
                    first_seen_at=t0,
                    last_seen_at=t0,
                    availability=PostingAvailability.ACTIVE,
                )
            ],
        )
        # Job B: UNAVAILABLE on Source B
        job_b = CanonicalJob(
            canonical_job_id=cid_b,
            company_name="Corp Beta",
            current_revision_id=rev_b,
            first_seen_at=t1,
            last_seen_at=t1,
            availability=PostingAvailability.UNAVAILABLE,
            linked_source_keys=[sk_b],
            revisions=[
                PostingRevision(
                    revision_id=rev_b,
                    canonical_job_id=cid_b,
                    source_key=sk_b,
                    content_hash="sha256:" + "b" * 64,
                    title="Dev",
                    first_seen_at=t1,
                    last_seen_at=t1,
                    availability=PostingAvailability.UNAVAILABLE,
                )
            ],
        )

        storage.canonical_jobs.save_canonical_job(job_a)
        storage.canonical_jobs.save_canonical_job(job_b)
        storage.identity.save_source_identity(sk_a, cid_a, t0, t0)
        storage.identity.save_source_identity(sk_b, cid_b, t1, t1)

        storage.availability.save_source_availability(
            SourcePostingAvailability(
                source_key=sk_a,
                scope_id="gh_a",
                canonical_job_id=cid_a,
                availability=PostingAvailability.ACTIVE,
                first_seen_at=t0,
                last_seen_at=t0,
            )
        )
        storage.availability.save_source_availability(
            SourcePostingAvailability(
                source_key=sk_b,
                scope_id="an_b",
                canonical_job_id=cid_b,
                availability=PostingAvailability.UNAVAILABLE,
                first_seen_at=t1,
                last_seen_at=t1,
                miss_count=3,
            )
        )

        # Execute merge of B into A
        merge_op = execute_merge(
            surviving_id=cid_a,
            merged_id=cid_b,
            actor="admin",
            reason="Confirmed duplicate listing",
            canonical_repo=storage.canonical_jobs,
            identity_repo=storage.identity,
        )
        assert merge_op.surviving_canonical_id == cid_a

        # Recompute availability for surviving job A
        service.recompute_canonical_availability(cid_a)
        saved_a = storage.canonical_jobs.get_canonical_job(cid_a)
        assert saved_a is not None
        # Job A has sk_a (active) and sk_b (unavailable) -> remains ACTIVE!
        assert saved_a.availability == PostingAvailability.ACTIVE

        # Now execute reversal of the merge
        execute_reversal(
            operation_id=merge_op.operation_id,
            actor="admin",
            reason="False duplicate match reverted",
            canonical_repo=storage.canonical_jobs,
            identity_repo=storage.identity,
        )

        # Recompute availability for both jobs after reversal
        service.recompute_canonical_availability(cid_a)
        service.recompute_canonical_availability(cid_b)

        saved_a_after = storage.canonical_jobs.get_canonical_job(cid_a)
        saved_b_after = storage.canonical_jobs.get_canonical_job(cid_b)

        assert saved_a_after is not None
        assert saved_b_after is not None
        assert saved_a_after.availability == PostingAvailability.ACTIVE
        # Source B was unavailable, so Job B returns to its source's unavailable status
        assert saved_b_after.availability == PostingAvailability.UNAVAILABLE
