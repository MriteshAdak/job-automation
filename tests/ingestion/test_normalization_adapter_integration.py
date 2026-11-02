"""End-to-end integration tests from real source adapters through Normalizer into C06 (INGEST-02-S08)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    AcquisitionMethod,
    EmploymentType,
    InventorySemantics,
    WorkplaceType,
)
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.normalization import DefaultNormalizer
from job_automation.sources.adapters.arbeitnow import ArbeitnowAdapter
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
from job_automation.sources.adapters.manual_text import ManualTextAdapter
from job_automation.sources.adapters.raw import InMemoryRawCaptureSink
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
)
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_arbeitnow_config,
    build_arbeitnow_source,
    load_fixture,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sources"


@pytest.fixture
def manual_effective_source() -> EffectiveSource:
    config = SourceConfig(
        source_key="manual_inbox",
        provider="manual",
        board_id="inbox",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://inbox/text",
        access_rules=json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "direct-input",
                "permitted_methods": ["manual_import"],
            }
        ),
        attribution_rules="none_required",
        enabled=True,
        inventory_semantics=InventorySemantics.SEARCH_RESULTS,
    )
    return EffectiveSource(
        config=config,
        access_review=AccessReview(
            status=AccessReviewStatus.PERMITTED,
            reviewed_at="2026-10-28T00:00:00Z",
            evidence_ref="direct-input",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-v1:manual_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox/text",
        ),
    )


@pytest.fixture
def arbeitnow_effective_source() -> EffectiveSource:
    return build_arbeitnow_source()


def test_manual_text_adapter_to_normalization(manual_effective_source: EffectiveSource) -> None:
    """ManualTextAdapter produces C05 draft that normalizes cleanly into C06 NormalizedPosting."""
    sink = InMemoryRawCaptureSink()
    adapter = ManualTextAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/vacancies/0007",
        text="<p>Senior Python Entwickler mit FastAPI gesucht.</p>",
        source_posting_id="0007",
        title="Senior Python Entwickler",
        company="Muster GmbH",
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 1
    raw_posting = page.items[0]

    draft_res = adapter.draft_posting(raw_posting)
    assert draft_res.draft is not None

    normalizer = DefaultNormalizer(raw_reader=sink)
    posting, issues = normalizer.normalize(draft_res.draft)

    assert posting is not None
    assert isinstance(posting, NormalizedPosting)
    assert posting.title == "Senior Python Entwickler"
    assert posting.company_name_hint == "Muster GmbH"
    assert posting.source_key.source_posting_id == "0007"
    assert posting.description_clean == "Senior Python Entwickler mit FastAPI gesucht."
    assert posting.raw_reference == raw_posting.raw_payload_ref
    assert posting.raw_content_hash == raw_posting.raw_content_hash


def test_manual_csv_adapter_to_normalization(manual_effective_source: EffectiveSource) -> None:
    """ManualCsvAdapter produces rows with preserved IDs and unknown missing units in C06."""
    sink = InMemoryRawCaptureSink()
    csv_path = FIXTURES_DIR / "manual" / "csv" / "valid_jobs.csv"

    adapter = ManualCsvAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        csv_path=csv_path,
        page_size=10,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) >= 2

    # Row 1 has ID '0007'
    raw_0007 = next(
        item for item in page.items if item.source_key.source_posting_id == "0007"
    )
    draft_res = adapter.draft_posting(raw_0007)
    assert draft_res.draft is not None

    normalizer = DefaultNormalizer(raw_reader=sink)
    posting, issues = normalizer.normalize(draft_res.draft)

    assert posting is not None
    # Preserves leading zeros
    assert posting.source_key.source_posting_id == "0007"
    assert posting.title == "Senior Python Developer"
    assert posting.company_name_hint == "Tech GmbH"
    assert len(posting.locations) == 1
    assert posting.locations[0].city == "Berlin"
    # Compensation raw was '75.000 - 85.000 EUR' without period -> stays None with warning
    assert posting.compensation is None
    assert any(iss.code == "unsupported_representation" for iss in issues)


def test_arbeitnow_adapter_to_normalization(arbeitnow_effective_source: EffectiveSource) -> None:
    """ArbeitnowAdapter drafts normalize into C06 with unpromoted created_at and honest workplace."""
    page_1_bytes = load_fixture("page_1.json")
    sink = InMemoryRawCaptureSink()
    transport = FakeTransport(
        {
            "https://www.arbeitnow.com/api/job-board-api?page=1": (
                200,
                {"Content-Type": "application/json"},
                page_1_bytes,
            )
        }
    )

    adapter = ArbeitnowAdapter(
        effective_source=arbeitnow_effective_source,
        capture_sink=sink,
        transport=transport,
    )

    page = adapter.fetch_page(build_arbeitnow_config())
    assert len(page.items) == 2

    normalizer = DefaultNormalizer(raw_reader=sink)

    # Job 1: kueche-und-co-sachbearbeiter-0007 (remote=false, created_at=1730035200)
    draft_res_1 = adapter.draft_posting(page.items[0])
    assert draft_res_1.draft is not None
    posting_1, issues_1 = normalizer.normalize(draft_res_1.draft)

    assert posting_1 is not None
    assert posting_1.title == "Sachbearbeiter (m/w/d) Vertriebsinnendienst"
    assert posting_1.company_name_hint == "Küche & Co GmbH"
    assert posting_1.employment_type == EmploymentType.FULL_TIME
    # Remote=False stays UNKNOWN (does not imply onsite)
    assert posting_1.workplace_type == WorkplaceType.UNKNOWN
    # created_at stays unpromoted (source_published_at is None)
    assert posting_1.source_published_at is None
    # Missing salary stays unknown (None)
    assert posting_1.compensation is None
    # Absent deadline is not invented (None)
    assert posting_1.source_deadline_at is None

    # Job 2: tech-startup-software-engineer-0042 (remote=true)
    draft_res_2 = adapter.draft_posting(page.items[1])
    assert draft_res_2.draft is not None
    posting_2, issues_2 = normalizer.normalize(draft_res_2.draft)

    assert posting_2 is not None
    assert posting_2.title == "Software Engineer (m/f/d)"
    assert posting_2.workplace_type == WorkplaceType.REMOTE
    # Remote does NOT imply worldwide
    assert posting_2.remote_eligibility_restrictions == []
