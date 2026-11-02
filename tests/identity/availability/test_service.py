"""Tests for AvailabilityService execution, sightings, misses, and summaries (IDENTITY-02-S07)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.availability.service import AvailabilityService
from job_automation.storage.engine import StorageEngine


class TestService:
    def test_end_to_end_sighting_and_canonical_summary(self, tmp_path) -> None:
        db_path = tmp_path / "service_e2e.db"
        storage = StorageEngine(db_path=db_path)
        storage.migrate()
        service = AvailabilityService(storage=storage)

        t0 = datetime(2026, 10, 28, 8, 0, 0, tzinfo=timezone.utc)
        cid = uuid.uuid4()
        rev_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="de", source_posting_id="101")

        # Seed canonical job and source identity
        job = CanonicalJob(
            canonical_job_id=cid,
            company_name="Innovatech GmbH",
            current_revision_id=rev_id,
            first_seen_at=t0,
            last_seen_at=t0,
            availability=PostingAvailability.ACTIVE,
            linked_source_keys=[sk],
            revisions=[
                PostingRevision(
                    revision_id=rev_id,
                    canonical_job_id=cid,
                    source_key=sk,
                    content_hash="sha256:" + "c" * 64,
                    title="Backend Engineer",
                    first_seen_at=t0,
                    last_seen_at=t0,
                    availability=PostingAvailability.ACTIVE,
                )
            ],
        )
        storage.canonical_jobs.save_canonical_job(job)
        storage.identity.save_source_identity(sk, cid, t0, t0)

        # Process manifest containing posting "101"
        m = FetchManifest(
            run_id=uuid.uuid4(),
            source_key="arbeitnow_de",
            scope_id="an_de",
            start_time=t0,
            end_time=t0,
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            page_count=1,
            observed_posting_identities=["101"],
        )
        result = service.process_manifest(m)
        assert result.positive_observations_count == 1
        assert result.is_replay is False

        # Verify summary
        summary = service.get_canonical_availability_summary(cid)
        assert summary is not None
        assert summary.canonical_job_id == cid
        assert summary.company_name == "Innovatech GmbH"
        assert summary.canonical_availability == PostingAvailability.ACTIVE
        assert summary.linked_sources_count == 1
        assert summary.active_sources_count == 1
        assert len(summary.source_states) == 1
        assert summary.source_states[0].source_key == sk

        # Verify decisions query
        decisions = service.get_decisions(canonical_job_id=cid)
        assert len(decisions) >= 1

