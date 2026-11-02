"""Tests for C04 FetchManifest outcome matrix and exact identity preservation (INGEST-01-S07)."""

import uuid
from datetime import datetime, timezone

from job_automation.contracts.adapter_results import Continuation, DraftResult, RecordIssue
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.manifests import build_fetch_manifest
from job_automation.ingestion.models import PageReceipt
from job_automation.sources.models import EffectiveSource
from job_automation.sources.validation import validate_source_config


def _make_source() -> EffectiveSource:
    cfg = SourceConfig(
        source_key="man_src",
        provider="prov_m",
        board_id="board_m",
        acquisition_method=AcquisitionMethod.API,
        base_url="https://example.invalid",
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
        attribution_rules='{"status": "none_required"}',
    )
    return validate_source_config(cfg)


def test_manifest_complete_outcome():
    eff = _make_source()
    now = datetime.now(timezone.utc)
    run_id = uuid.uuid4()

    draft = SourceJobDraft(
        raw_reference="raw://1",
        source_key=SourceKey(provider="prov_m", board_id="board_m", source_posting_id="0007"),
        fetch_time=now,
        original_fields={},
        source_mapped_fields={"title": "Dev", "source_url": "https://example.invalid"},
    )
    receipt = PageReceipt(
        traversal_id="trav_1",
        page_index=1,
        attempt_count=1,
        continuation_in=None,
        continuation_out=None,
        source_key="man_src",
        scope_id="prov_m_board_m",
        adapter_name="test-v1",
        raw_response_refs=["raw://resp_1"],
        raw_response_hashes=["sha256:" + "1" * 64],
        observed_posting_ids=["0007"],
        raw_record_refs=["raw://1"],
        draft_results=[DraftResult(raw_reference="raw://1", draft=draft, issues=[])],
        issues=[],
        fetch_time=now,
        exhausted=True,
    )

    manifest = build_fetch_manifest(
        run_id=run_id,
        effective_source=eff,
        start_time=now,
        end_time=now,
        cursor_in=None,
        cursor_out=None,
        receipts=[receipt],
    )

    assert manifest.outcome == FetchOutcome.COMPLETE
    assert manifest.cursor_out is None
    assert manifest.page_count == 1
    # Leading zeros in identity string MUST be strictly preserved
    assert manifest.observed_posting_identities == ["0007"]
    assert manifest.error is None


def test_manifest_blocking_record_error_yields_partial():
    eff = _make_source()
    now = datetime.now(timezone.utc)
    run_id = uuid.uuid4()

    # Record 1 valid
    draft1 = SourceJobDraft(
        raw_reference="raw://1",
        source_key=SourceKey(provider="prov_m", board_id="board_m", source_posting_id="j1"),
        fetch_time=now,
        original_fields={},
        source_mapped_fields={"title": "Dev", "source_url": "https://example.invalid"},
    )
    # Record 2 blocking error
    issue = RecordIssue(
        input_ref="raw://2",
        input_hash="sha256:" + "2" * 64,
        code="missing_title",
        severity="error",
        message="Title missing",
    )
    draft_res2 = DraftResult(raw_reference="raw://2", draft=None, issues=[issue])

    receipt = PageReceipt(
        traversal_id="trav_1",
        page_index=1,
        attempt_count=1,
        source_key="man_src",
        scope_id="prov_m_board_m",
        adapter_name="test-v1",
        observed_posting_ids=["j1", "j2"],
        draft_results=[
            DraftResult(raw_reference="raw://1", draft=draft1, issues=[]),
            draft_res2,
        ],
        issues=[issue],
        fetch_time=now,
        exhausted=True,
    )

    manifest = build_fetch_manifest(
        run_id=run_id,
        effective_source=eff,
        start_time=now,
        end_time=now,
        cursor_in=None,
        cursor_out=None,
        receipts=[receipt],
    )

    # Blocking record errors prevent COMPLETE status
    assert manifest.outcome == FetchOutcome.PARTIAL
    assert manifest.error is not None
    assert "blocking_record_issues" in str(manifest.error.details)

