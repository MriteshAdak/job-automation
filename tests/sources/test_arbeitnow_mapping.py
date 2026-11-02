"""C05 field mapping, type validation, timestamp policy, and attribution tests (SOURCE-03-S05)."""

from __future__ import annotations

import json
import pytest

from job_automation.contracts.adapter_results import DraftResult
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.postings import SourceJobDraft
from job_automation.sources.adapters.arbeitnow import (
    ATTRIBUTION_LINK,
    ATTRIBUTION_NOTICE,
    MAPPING_ID,
    build_page_url,
)
from tests.sources.arbeitnow_helpers import (
    FakeTransport,
    build_adapter,
    build_arbeitnow_config,
    load_fixture,
)


def test_standard_fields_mapped_correctly_from_fixture() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)

    page = adapter.fetch_page(build_arbeitnow_config())
    assert len(page.items) == 2

    # Job 1: Küche & Co (onsite, Hamburg)
    res1: DraftResult = adapter.draft_posting(page.items[0])
    assert res1.draft is not None
    draft1: SourceJobDraft = res1.draft

    mapped1 = draft1.source_mapped_fields
    assert mapped1["title"] == "Sachbearbeiter (m/w/d) Vertriebsinnendienst"
    assert mapped1["company_name_hint"] == "Küche & Co GmbH"
    assert "<strong>Sachbearbeiter</strong>" in mapped1["description"]
    assert mapped1["source_url"] == "https://www.arbeitnow.com/view/kueche-und-co-sachbearbeiter-0007"
    assert mapped1["application_url"] is None
    assert mapped1["locations_raw"] == "Hamburg, Deutschland"
    assert mapped1["workplace_type_raw"] is False  # boolean False, not string or None
    assert mapped1["employment_type_raw"] == ["Vollzeit"]
    assert mapped1["compensation_raw"] is None
    assert mapped1["source_published_raw"] is None  # U05 decision
    assert mapped1["source_deadline_raw"] is None
    assert mapped1["mapping_version"] == MAPPING_ID
    assert mapped1["attribution"]["notice"] == ATTRIBUTION_NOTICE
    assert mapped1["attribution"]["link"] == ATTRIBUTION_LINK

    # Original fields preserved
    assert draft1.original_fields["created_at"] == 1730035200
    assert draft1.original_fields["tags"] == ["Office", "Sales", "CRM"]

    # Job 2: Tech Startup (remote, Berlin)
    res2: DraftResult = adapter.draft_posting(page.items[1])
    assert res2.draft is not None
    draft2: SourceJobDraft = res2.draft
    assert draft2.source_mapped_fields["workplace_type_raw"] is True  # boolean True


def test_remote_false_preserved_as_boolean_without_coercion() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    res = adapter.draft_posting(page.items[0])
    assert res.draft is not None
    # Must be bool False, not string "false" or enum
    assert res.draft.source_mapped_fields["workplace_type_raw"] is False
    assert isinstance(res.draft.source_mapped_fields["workplace_type_raw"], bool)


def test_remote_null_mapped_to_none() -> None:
    missing_fields_bytes = load_fixture("missing_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, missing_fields_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 1 has remote: null
    res = adapter.draft_posting(page.items[1])
    assert res.draft is not None
    assert res.draft.source_mapped_fields["workplace_type_raw"] is None


def test_remote_invalid_type_yields_blocking_error() -> None:
    # Build raw posting directly from JSON containing string remote
    payload = b"""{
        "data": [{"slug": "bad-remote-01", "company_name": "C", "title": "T", "description": "<p>D</p>", "remote": "true", "url": "https://www.arbeitnow.com/view/bad-remote-01"}],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, payload)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    assert len(page.items) == 1
    res = adapter.draft_posting(page.items[0])

    assert res.draft is None
    assert any(iss.code == "invalid_remote_type" for iss in res.issues)


def test_job_types_empty_list_preserved_as_empty_list() -> None:
    page_term_bytes = load_fixture("page_terminal.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_term_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # page_terminal.json has job_types: []
    res = adapter.draft_posting(page.items[0])
    assert res.draft is not None
    assert res.draft.source_mapped_fields["employment_type_raw"] == []


def test_job_types_null_mapped_to_none() -> None:
    missing_fields_bytes = load_fixture("missing_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, missing_fields_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 1 in missing_fields.json has job_types: null
    res = adapter.draft_posting(page.items[1])
    assert res.draft is not None
    assert res.draft.source_mapped_fields["employment_type_raw"] is None


def test_job_types_invalid_type_yields_blocking_error() -> None:
    payload = b"""{
        "data": [{"slug": "bad-jt-01", "company_name": "C", "title": "T", "description": "<p>D</p>", "job_types": "Vollzeit", "url": "https://www.arbeitnow.com/view/bad-jt-01"}],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, payload)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    res = adapter.draft_posting(page.items[0])
    assert res.draft is None
    assert any(iss.code == "invalid_job_types_type" for iss in res.issues)


def test_created_at_integer_preserved_in_original_fields_and_published_raw_is_none() -> None:
    timestamps_bytes = load_fixture("timestamps.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, timestamps_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 0: unix seconds 1704067200
    res0 = adapter.draft_posting(page.items[0])
    assert res0.draft is not None
    assert res0.draft.original_fields["created_at"] == 1704067200
    assert res0.draft.source_mapped_fields["source_published_raw"] is None

    # Item 1: created_at null
    res1 = adapter.draft_posting(page.items[1])
    assert res1.draft is not None
    assert res1.draft.original_fields["created_at"] is None
    assert res1.draft.source_mapped_fields["source_published_raw"] is None


def test_created_at_string_type_yields_blocking_error() -> None:
    timestamps_bytes = load_fixture("timestamps.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, timestamps_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 3: "created_at": "2024-01-01T00:00:00Z" (string -> invalid)
    res3 = adapter.draft_posting(page.items[3])
    assert res3.draft is None
    assert any(iss.code == "invalid_created_at_type" for iss in res3.issues)


def test_created_at_bool_type_yields_blocking_error() -> None:
    payload = b"""{
        "data": [{"slug": "bad-cat-bool", "company_name": "C", "title": "T", "description": "<p>D</p>", "created_at": true, "url": "https://www.arbeitnow.com/view/bad-cat-bool"}],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, payload)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    res = adapter.draft_posting(page.items[0])
    assert res.draft is None
    assert any(iss.code == "invalid_created_at_type" for iss in res.issues)


def test_missing_or_empty_description_yields_blocking_error() -> None:
    missing_fields_bytes = load_fixture("missing_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, missing_fields_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 0 has description: ""
    res0 = adapter.draft_posting(page.items[0])
    assert res0.draft is None
    assert any(iss.code == "missing_posting_text" for iss in res0.issues)
    assert res0.raw_reference == page.items[0].raw_payload_ref


def test_missing_url_yields_blocking_error() -> None:
    missing_fields_bytes = load_fixture("missing_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, missing_fields_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    # Item 2 has no url field
    res2 = adapter.draft_posting(page.items[2])
    assert res2.draft is None
    assert any(iss.code == "missing_source_url" for iss in res2.issues)


def test_missing_title_produces_draft_with_warning() -> None:
    payload = b"""{
        "data": [{"slug": "no-title-01", "company_name": "C", "description": "<p>Valid description</p>", "url": "https://www.arbeitnow.com/view/no-title-01"}],
        "links": {"next": null},
        "meta": {"current_page": 1}
    }"""
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, payload)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    res = adapter.draft_posting(page.items[0])
    assert res.draft is not None
    assert res.draft.source_mapped_fields["title"] is None
    assert any(iss.code == "missing_title" and iss.severity == "warning" for iss in res.issues)


def test_unknown_fields_preserved_in_original_fields() -> None:
    unknown_fields_bytes = load_fixture("unknown_fields.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, unknown_fields_bytes)
    adapter, _ = build_adapter(transport=transport)
    page = adapter.fetch_page(build_arbeitnow_config())

    res = adapter.draft_posting(page.items[0])
    assert res.draft is not None
    orig = res.draft.original_fields
    assert orig["salary_min"] == 60000
    assert orig["salary_max"] == 80000
    assert orig["visa_sponsorship"] is False
    assert orig["unknown_future_field"] == "some_value"
    assert orig["nested_unknown"] == {"key": "value", "list": [1, 2, 3]}


def test_draft_posting_works_after_serialization_and_reload() -> None:
    page_1_bytes = load_fixture("page_1.json")
    transport = FakeTransport()
    transport.add(build_page_url(1), 200, {}, page_1_bytes)
    adapter1, _ = build_adapter(transport=transport)
    page = adapter1.fetch_page(build_arbeitnow_config())

    raw_item = page.items[0]
    # Serialize and re-parse raw item via pydantic
    raw_dict = raw_item.model_dump(mode="json")
    from job_automation.contracts.postings import RawPosting
    reloaded_raw = RawPosting.model_validate(raw_dict)

    # Use a fresh adapter instance with no prior state
    adapter2, _ = build_adapter()
    res = adapter2.draft_posting(reloaded_raw)

    assert res.draft is not None
    assert res.draft.source_key == raw_item.source_key
    assert res.draft.source_mapped_fields["title"] == "Sachbearbeiter (m/w/d) Vertriebsinnendienst"

