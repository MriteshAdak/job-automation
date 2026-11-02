"""Tests for ManualTextAdapter (SOURCE-02-S04)."""

from __future__ import annotations

import json
from pathlib import Path
import socket
import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
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

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "sources" / "manual" / "text"


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
            scope_id="scope-v1:manual_text_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="inbox",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox/text",
        ),
    )


@pytest.fixture(autouse=True)
def guard_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no socket calls or network requests occur during manual import."""
    def fail_socket(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Network activity forbidden during manual adapter execution!")

    monkeypatch.setattr(socket, "socket", fail_socket)


def test_manual_text_adapter_string_success(manual_effective_source: EffectiveSource) -> None:
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
    assert page.exhausted
    assert page.continuation_out is None
    assert page.record_count == 1
    assert page.items[0].source_key.source_posting_id == "0007"
    assert page.items[0].raw_payload == "<p>Senior Python Entwickler mit FastAPI gesucht.</p>"

    # Draft posting
    draft_res = adapter.draft_posting(page.items[0])
    assert draft_res.draft is not None
    assert draft_res.draft.source_mapped_fields["title"] == "Senior Python Entwickler"
    assert draft_res.draft.source_mapped_fields["company_name_hint"] == "Muster GmbH"


def test_manual_text_adapter_from_file(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualTextAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/vacancies/file_job",
        text_path="valid_job.txt",
        input_base_path=FIXTURES_DIR,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 1
    assert page.exhausted
    assert "Senior Python Entwickler" in page.items[0].raw_payload

    # No title was explicitly provided, so there is a warning issue
    assert any(iss.code == "missing_title" and iss.severity == "warning" for iss in page.issues)


def test_manual_text_adapter_missing_text(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    adapter = ManualTextAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/vacancies/url_only",
        text="   ",  # Blank
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 0
    assert page.exhausted
    assert any(iss.code == "missing_posting_text" and iss.severity == "error" for iss in page.issues)


def test_manual_text_adapter_invalid_urls(manual_effective_source: EffectiveSource) -> None:
    sink = InMemoryRawCaptureSink()
    invalid_urls = [
        "file:///C:/secret.txt",
        "javascript:alert(1)",
        "https://user:pass@example.invalid/job",
    ]
    for bad_url in invalid_urls:
        adapter = ManualTextAdapter(
            effective_source=manual_effective_source,
            capture_sink=sink,
            source_url=bad_url,
            text="Valid text here",
        )
        page = adapter.fetch_page(manual_effective_source.config)
        assert len(page.items) == 0
        assert page.exhausted
        assert any("invalid_source_url" in iss.code for iss in page.issues)


def test_manual_text_adapter_hostile_content_preserved_as_inert_data(
    manual_effective_source: EffectiveSource,
) -> None:
    sink = InMemoryRawCaptureSink()
    hostile_path = FIXTURES_DIR / "hostile_job.txt"
    adapter = ManualTextAdapter(
        effective_source=manual_effective_source,
        capture_sink=sink,
        source_url="https://jobs.example.invalid/hostile",
        text_path=hostile_path,
    )

    page = adapter.fetch_page(manual_effective_source.config)
    assert len(page.items) == 1
    raw = page.items[0]
    assert "=cmd|' /C calc'!A0" in raw.raw_payload
    assert "rm -rf /" in raw.raw_payload
    assert "<script>alert('xss')</script>" in raw.raw_payload

