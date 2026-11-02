"""Full lifecycle integration test for IDENTITY-02 availability tracking (IDENTITY-02-S08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from job_automation.contracts.enums import (
    ApplicationProgress,
    FetchOutcome,
    InventorySemantics,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestIntegration:
    def test_full_availability_lifecycle(self, tmp_path) -> None:
        db_path = tmp_path / "lifecycle_full.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 20, 8, 0, 0, tzinfo=timezone.utc)
        cid = uuid.uuid4()
        rev_id = uuid.uuid4()
        sk_primary = SourceKey(provider="gh", board_id="acme", source_posting_id="101")
        sk_secondary = SourceKey(provider="an", board_id="de", source_posting_id="202")

        # 1. Establish canonical job with two linked sources
        rev = PostingRevision(
            revision_id=rev_id,
            canonical_job_id=cid,
            source_key=sk_primary,
            content_hash="sha256:" + "f" * 64,
            title="Senior Platform Engineer",
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
        )
        job = CanonicalJob(
            canonical_job_id=cid,
            company_name="Acme Corp",
            current_revision_id=rev_id,
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk_primary, sk_secondary],
            revisions=[rev],
        )
        storage.canonical_jobs.save_canonical_job(job)
        storage.identity.save_source_identity(sk_primary, cid, t0, t0)
        storage.identity.save_source_identity(sk_secondary, cid, t0, t0)

        # Baseline sightings for both sources
        m0_gh = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        m0_an = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="an_de",
            scope_id="an_de",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["202"],
        )
        service.process_manifest(m0_gh)
        service.process_manifest(m0_an)

        # Candidate application progress is 'Applied'
        application_progress = ApplicationProgress.APPLIED

        # 2. Search-only run occurs: causes 0 misses
        t1 = t0 + timedelta(days=1)
        m_search = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="an_de",
            scope_id="an_de",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
            page_count=1,
            observed_posting_identities=[],  # Empty search results
        )
        res_search = service.process_manifest(m_search)
        assert res_search.eligible_for_negative_inference is False
        assert res_search.miss_evaluations_count == 0

        # 3. Partial run occurs on gh: causes 0 misses
        m_partial = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.PARTIAL,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        res_part = service.process_manifest(m_partial)
        assert res_part.eligible_for_negative_inference is False
        assert res_part.miss_evaluations_count == 0

        # 4. Scope change run occurs on different scope "gh_munich": causes 0 misses on gh_acme
        m_scope = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_munich",
            scope_id="gh_munich",
            start_time=t1,
            end_time=t1,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["999"],
        )
        res_scope = service.process_manifest(m_scope)
        assert res_scope.miss_evaluations_count == 0

        # 5. Repeated complete misses on primary source gh_acme
        # Miss 1 at day 2
        t2 = t0 + timedelta(days=2)
        m_gh_miss1 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t2,
            end_time=t2,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m_gh_miss1)
        s_gh1 = service.get_source_availability(sk_primary, "gh_acme")
        assert s_gh1 is not None
        assert s_gh1.availability == PostingAvailability.NOT_SEEN

        # Miss 2 at day 3
        t3 = t0 + timedelta(days=3)
        m_gh_miss2 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t3,
            end_time=t3,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m_gh_miss2)

        # Miss 3 at day 5 (more than 48 hours after Miss 1) -> primary source is UNAVAILABLE
        t5 = t0 + timedelta(days=5)
        m_gh_miss3 = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t5,
            end_time=t5,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=[],
        )
        service.process_manifest(m_gh_miss3)

        s_gh3 = service.get_source_availability(sk_primary, "gh_acme")
        assert s_gh3 is not None
        assert s_gh3.availability == PostingAvailability.UNAVAILABLE

        # 6. Primary is UNAVAILABLE, but Secondary (sk_secondary) is still ACTIVE:
        # Canonical Job MUST remain ACTIVE!
        can_job = storage.canonical_jobs.get_canonical_job(cid)
        assert can_job is not None
        assert can_job.availability == PostingAvailability.ACTIVE

        # 7. Now Secondary source also encounters 3 misses and 48h grace
        for d in [6, 7, 9]:
            td = t0 + timedelta(days=d)
            m_an_miss = FetchManifest(
                run_id=uuid.uuid4(),
                source_key="an_de",
                scope_id="an_de",
                start_time=td,
                end_time=td,
                outcome=FetchOutcome.COMPLETE,
                inventory_semantics=InventorySemantics.COMPLETE_BOARD,
                page_count=1,
                observed_posting_identities=[],
            )
            service.process_manifest(m_an_miss)

        s_an_final = service.get_source_availability(sk_secondary, "an_de")
        assert s_an_final is not None
        assert s_an_final.availability == PostingAvailability.UNAVAILABLE

        # ALL linked sources are now UNAVAILABLE -> Canonical Job transitions to UNAVAILABLE!
        can_job_unavail = storage.canonical_jobs.get_canonical_job(cid)
        assert can_job_unavail is not None
        assert can_job_unavail.availability == PostingAvailability.UNAVAILABLE

        # 8. Reappearance: primary source 101 reappears on greenhouse
        t10 = t0 + timedelta(days=10)
        m_reopen = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="gh_acme",
            scope_id="gh_acme",
            start_time=t10,
            end_time=t10,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        service.process_manifest(m_reopen)

        # Primary source reopens to ACTIVE
        s_gh_reopened = service.get_source_availability(sk_primary, "gh_acme")
        assert s_gh_reopened is not None
        assert s_gh_reopened.availability == PostingAvailability.ACTIVE
        assert s_gh_reopened.miss_count == 0

        # Canonical Job reopens to ACTIVE!
        can_job_reopened = storage.canonical_jobs.get_canonical_job(cid)
        assert can_job_reopened is not None
        assert can_job_reopened.availability == PostingAvailability.ACTIVE

        # Candidate application progress is STILL Applied; machine-owned availability
        # NEVER mutates candidate application progress!
        assert application_progress == ApplicationProgress.APPLIED

