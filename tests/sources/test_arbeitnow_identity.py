"""Source identity extraction, slug preservation, and URL fallback tests (SOURCE-03-S04)."""

from __future__ import annotations

import hashlib
import json
import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.primitives import SourceKey
from job_automation.sources.adapters.arbeitnow import (
    BOARD_ID,
    PROVIDER,
    build_page_url,
)
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    load_fixture,
)


def test_slug_preserved_with_exact_casing_and_leading_zeros() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert len(page.items) == 2
    item1 = page.items[0]
    # "kueche-und-co-sachbearbeiter-0007" must not have "0007" converted to "7"
    assert item1.source_key.source_posting_id == "kueche-und-co-sachbearbeiter-0007"
    assert item1.source_key.provider == PROVIDER
    assert item1.source_key.board_id == BOARD_ID

    item2 = page.items[1]
    assert item2.source_key.source_posting_id == "tech-startup-software-engineer-0042"


def test_leading_zero_slug_distinct_from_stripped_slug() -> None:
    payload = b"""{
        "data": [
            {"slug": "job-0007", "company_name": "A", "title": "T1", "description": "<p>D</p>", "url": "https://www.arbeitnow.com/view/job-0007"},
            {"slug": "job-7", "company_name": "A", "title": "T2", "description": "<p>D</p>", "url": "https://www.arbeitnow.com/view/job-7"}
        ],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, payload)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert len(page.items) == 2
    assert page.items[0].source_key.source_posting_id == "job-0007"
    assert page.items[1].source_key.source_posting_id == "job-7"
    assert page.items[0].source_key != page.items[1].source_key


def test_duplicate_slug_preserved_as_separate_raw_postings() -> None:
    dup_slug_bytes = load_fixture("duplicate_slug.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, dup_slug_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert len(page.items) == 2
    # Both items have identical source_key
    assert page.items[0].source_key == page.items[1].source_key
    assert page.items[0].source_key.source_posting_id == "same-slug-0001"
    # But different payloads and different envelope hashes
    assert page.items[0].raw_content_hash != page.items[1].raw_content_hash
    assert page.items[0].raw_payload != page.items[1].raw_payload


def test_url_fallback_when_slug_absent_or_blank() -> None:
    url_target = "https://www.arbeitnow.com/view/manager-y-ag-0002"
    expected_hash = hashlib.sha256(url_target.encode("utf-8")).hexdigest()
    expected_id = f"url-v1:sha256:{expected_hash}"

    missing_fields_bytes = load_fixture("missing_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, missing_fields_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    # Record index 2 in missing_fields.json has no slug but has url
    # Let's find the item that used URL fallback
    fallback_items = [
        item for item in page.items if item.source_key.source_posting_id == expected_id
    ]
    assert len(fallback_items) == 1
    assert fallback_items[0].source_key.provider == PROVIDER
    assert fallback_items[0].source_key.board_id == BOARD_ID


def test_invalid_slug_type_generates_record_issue_and_preserves_valid_neighbors() -> None:
    wrong_types_bytes = load_fixture("wrong_types.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, wrong_types_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    # In wrong_types.json: record 1 has slug=12345 (integer -> error)
    # record 2 has valid slug="ok-slug-0002"
    assert len(page.items) == 1
    assert page.items[0].source_key.source_posting_id == "ok-slug-0002"

    slug_issues = [iss for iss in page.issues if iss.code == "invalid_slug_type"]
    assert len(slug_issues) == 1
    assert slug_issues[0].record_index == 1
    assert slug_issues[0].field_path == "data[0].slug"
    assert slug_issues[0].category == ErrorCategory.VALIDATION


def test_record_with_no_slug_and_no_url_produces_missing_posting_identity_issue() -> None:
    no_id_payload = b"""{
        "data": [
            {"company_name": "No ID GmbH", "title": "Job Without ID", "description": "<p>Content</p>"},
            {"slug": "valid-slug-0001", "company_name": "Valid GmbH", "title": "Valid Job", "description": "<p>Content</p>", "url": "https://www.arbeitnow.com/view/valid-slug-0001"}
        ],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, no_id_payload)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())

    assert len(page.items) == 1
    assert page.items[0].source_key.source_posting_id == "valid-slug-0001"

    missing_id_issues = [
        iss for iss in page.issues if iss.code == "missing_posting_identity"
    ]
    assert len(missing_id_issues) == 1
    assert missing_id_issues[0].record_index == 1
    assert missing_id_issues[0].severity == "error"

