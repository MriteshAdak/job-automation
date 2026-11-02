"""Tests for manifest eligibility, negative inference boundaries, and decision matrix (IDENTITY-02-S02)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import FetchOutcome, InventorySemantics
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest
from job_automation.identity.availability.evidence import (
    compute_manifest_fingerprint,
    is_manifest_eligible_for_negative_inference,
)


def _make_manifest(
    outcome: FetchOutcome = FetchOutcome.COMPLETE,
    semantics: InventorySemantics = InventorySemantics.COMPLETE_BOARD,
    error: ClassifiedError | None = None,
    scope_id: str = "scope-v1:valid",
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> FetchManifest:
    now = datetime.now(timezone.utc)
    return FetchManifest(
        run_id=uuid.uuid4(),
        source_key="test_src",
        scope_id=scope_id,
        start_time=start_time or now,
        end_time=end_time or now,
        outcome=outcome,
        inventory_semantics=semantics,
        error=error,
        page_count=1,
        observed_posting_identities=["p1", "p2"],
    )


class TestManifestEvidence:
    def test_complete_board_complete_outcome_is_eligible(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.COMPLETE_BOARD,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is True
        assert reason is None

    def test_partial_outcome_blocks_negative_inference(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.PARTIAL,
            semantics=InventorySemantics.COMPLETE_BOARD,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "cannot prove absence" in (reason or "")

    def test_failed_outcome_blocks_negative_inference(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.FAILED,
            semantics=InventorySemantics.COMPLETE_BOARD,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "cannot prove absence" in (reason or "")

    def test_search_results_blocks_negative_inference(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.SEARCH_RESULTS,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "search_results" in (reason or "")

    def test_filtered_feed_blocks_negative_inference(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.FILTERED_FEED,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "filtered_feed" in (reason or "")

    def test_manifest_with_error_blocks_negative_inference(self) -> None:
        err = ClassifiedError(
            category=ErrorCategory.RATE_LIMIT,
            message="Rate limit exceeded",
            recoverable=True,
        )
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.COMPLETE_BOARD,
            error=err,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "error" in (reason or "")

    def test_invalid_chronology_blocks_negative_inference(self) -> None:
        t1 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc)
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.COMPLETE_BOARD,
            start_time=t1,
            end_time=t2,
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "invalid chronology" in (reason or "")

    def test_empty_scope_blocks_negative_inference(self) -> None:
        manifest = _make_manifest(
            outcome=FetchOutcome.COMPLETE,
            semantics=InventorySemantics.COMPLETE_BOARD,
            scope_id="   ",
        )
        eligible, reason = is_manifest_eligible_for_negative_inference(manifest)
        assert eligible is False
        assert "scope_id" in (reason or "")

    def test_manifest_fingerprint_deterministic_and_sensitive(self) -> None:
        m1 = _make_manifest()
        fp1 = compute_manifest_fingerprint(m1)
        fp2 = compute_manifest_fingerprint(m1)
        assert fp1 == fp2
        assert fp1.startswith("sha256:")

        # Change observed identity order: must be invariant due to sorting
        m_permuted = m1.model_copy(update={"observed_posting_identities": ["p2", "p1"]})
        assert compute_manifest_fingerprint(m_permuted) == fp1

        # Change an ID: must produce different fingerprint
        m_diff = m1.model_copy(update={"observed_posting_identities": ["p1", "p3"]})
        assert compute_manifest_fingerprint(m_diff) != fp1
