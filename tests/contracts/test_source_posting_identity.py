"""Tests for C03 SourceConfig, C04 FetchManifest, C05 RawPosting/SourceJobDraft,
C06 NormalizedPosting, and C07 CanonicalJob/PostingRevision contracts.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import (
    AcquisitionMethod,
    CompensationProvenance,
    EmploymentType,
    FetchOutcome,
    InventorySemantics,
    PostingAvailability,
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.postings import (
    FetchManifest,
    JobCompensation,
    NormalizedPosting,
    RawPosting,
    SourceJobDraft,
    StructuredLocation,
)
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig


class TestSourcePostingIdentity:
    def test_source_key_scoping(self) -> None:
        sk1 = SourceKey(provider="provider-a", board_id="board-1", source_posting_id="42")
        sk2 = SourceKey(provider="provider-a", board_id="board-2", source_posting_id="42")
        assert sk1 != sk2

    def test_c03_source_config(self) -> None:
        cfg = SourceConfig(
            source_key="arbeitnow_de",
            provider="arbeitnow",
            board_id="default",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://job-board-api.com/api/v1/jobs",
            access_rules="Rate limit: 1 request/second",
            attribution_rules="Powered by Arbeitnow API",
            enabled=False,
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )
        assert cfg.enabled is False
        assert cfg.inventory_semantics == InventorySemantics.FILTERED_FEED

    def test_c04_fetch_manifest(self) -> None:
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        manifest = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow_de",
            scope_id="category-tech",
            start_time=now,
            end_time=now,
            cursor_in=None,
            cursor_out="cursor_page_2",
            page_count=1,
            raw_response_refs=["raw_page_1.json"],
            observed_posting_identities=["post-101", "post-102"],
            outcome=FetchOutcome.PARTIAL,
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )
        assert manifest.outcome == FetchOutcome.PARTIAL
        assert manifest.cursor_out == "cursor_page_2"

    def test_c05_raw_posting_and_source_job_draft(self) -> None:
        sk = SourceKey(provider="greenhouse", board_id="techcorp", source_posting_id="999")
        now = datetime.now(timezone.utc)
        raw = RawPosting(
            raw_payload_ref="snapshots/raw_999.json",
            raw_content_hash="sha256:" + "a" * 64,
            source_key=sk,
            fetch_time=now,
            raw_payload='{"id": 999, "role": "Python Dev"}',  # notice raw field is 'role', not 'title'
        )
        assert raw.source_key == sk

        draft = SourceJobDraft(
            raw_reference=raw.raw_payload_ref,
            source_key=sk,
            fetch_time=now,
            original_fields={"id": 999, "role": "Python Dev"},
            source_mapped_fields={"job_title_candidate": "Python Dev"},
        )
        assert draft.original_fields["id"] == 999

    def test_c06_normalized_posting_validation_and_fields(self) -> None:
        sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="12345")
        now = datetime.now(timezone.utc)

        # Missing title must fail
        with pytest.raises(ValidationError):
            NormalizedPosting(
                source_key=sk,
                normalizer_version="1.0",
                raw_reference="raw_ref",
                raw_content_hash="sha256:" + "b" * 64,
                company_name_hint="Acme Inc",
                title="",  # min_length=1
                description_clean="Clean description text",
                source_url="https://example.com/jobs/12345",
                observed_at=now,
            )

        # Multi-location, remote with restrictions, null deadline
        np = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            raw_reference="raw_ref",
            raw_content_hash="sha256:" + "b" * 64,
            company_name_hint="Acme GmbH",
            title="Senior Python Backend Engineer",
            description_clean="We are looking for a Senior Backend Engineer...",
            source_url="https://example.com/jobs/12345",
            application_url="https://example.com/jobs/12345/apply",
            locations=[
                StructuredLocation(raw_text="Berlin, Germany", country="DE", city="Berlin"),
                StructuredLocation(raw_text="Hamburg, Germany", country="DE", city="Hamburg"),
            ],
            workplace_type=WorkplaceType.REMOTE,
            remote_eligibility_restrictions=["DE"],
            employment_type=EmploymentType.FULL_TIME,
            compensation=JobCompensation(
                min_amount=Decimal("65000"),
                max_amount=Decimal("85000"),
                currency="EUR",
                period=SalaryPeriod.YEARLY,
                is_gross=True,
                provenance=CompensationProvenance.EMPLOYER_PROVIDED,
            ),
            advert_language="de",
            source_deadline_at=None,  # absent closing date stays null
            observed_at=now,
        )

        assert len(np.locations) == 2
        assert np.locations[0].city == "Berlin"
        assert np.workplace_type == WorkplaceType.REMOTE
        assert np.remote_eligibility_restrictions == ["DE"]
        assert np.source_deadline_at is None
        assert np.compensation is not None
        assert np.compensation.period == SalaryPeriod.YEARLY
        assert np.compensation.provenance == CompensationProvenance.EMPLOYER_PROVIDED

    def test_c07_canonical_job_and_revisions(self) -> None:
        can_id = uuid.uuid4()
        comp_id = uuid.uuid4()
        rev1_id = uuid.uuid4()
        rev2_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="1001")
        now = datetime.now(timezone.utc)

        rev1 = PostingRevision(
            revision_id=rev1_id,
            canonical_job_id=can_id,
            source_key=sk,
            content_hash="sha256:" + "1" * 64,
            title="Python Developer",
            first_seen_at=now,
            last_seen_at=now,
            source_urls=["https://example.com/jobs/1001"],
            application_urls=["https://example.com/jobs/1001/apply"],
            availability=PostingAvailability.ACTIVE,
        )

        rev2 = PostingRevision(
            revision_id=rev2_id,
            canonical_job_id=can_id,
            source_key=sk,
            content_hash="sha256:" + "2" * 64,
            title="Senior Python Developer",  # title changed in revision
            first_seen_at=now,
            last_seen_at=now,
            source_urls=["https://example.com/jobs/1001"],
            application_urls=["https://example.com/jobs/1001/apply_v2"],
            availability=PostingAvailability.ACTIVE,
        )

        can_job = CanonicalJob(
            canonical_job_id=can_id,
            canonical_company_id=comp_id,
            company_name="Tech Solutions GmbH",
            linked_source_keys=[sk],
            revisions=[rev1, rev2],
            current_revision_id=rev2_id,
            first_seen_at=now,
            last_seen_at=now,
            availability=PostingAvailability.ACTIVE,
            merge_lineage=["initial_registration", "revision_update_2"],
        )

        assert can_job.canonical_job_id == can_id
        assert len(can_job.revisions) == 2
        assert can_job.current_revision_id == rev2_id
        assert can_job.revisions[0].content_hash != can_job.revisions[1].content_hash

