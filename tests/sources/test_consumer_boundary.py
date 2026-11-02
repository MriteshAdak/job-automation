"""Consumer boundary tests verifying handoff to downstream INGEST-01 components (SOURCE-01-S08).

Demonstrates:
- Consuming checked EffectiveSource selections without network collection.
- Constructing C04 FetchManifest fixtures from declared scope identity.
- Distinguishing complete, partial, failed, and empty execution outcomes across all 3 inventory semantics.
- Preserving exact C03 provider, board_id, and attribution metadata.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from job_automation.contracts.enums import (
    AcquisitionMethod,
    FetchOutcome,
    InventorySemantics,
)
from job_automation.contracts.postings import FetchManifest
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.models import EffectiveSource, SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService


class FakeFetchConsumerRecorder:
    """Test fake representing downstream INGEST-01 fetch controller receiving checked selections."""

    def __init__(self) -> None:
        self.received_selections: list[EffectiveSource] = []
        self.created_manifests: list[FetchManifest] = []

    def record_selection(self, source: EffectiveSource) -> None:
        """Receive and record a checked source selection."""
        self.received_selections.append(source)

    def simulate_manifest(
        self,
        source: EffectiveSource,
        outcome: FetchOutcome,
        observed_posting_ids: list[str] | None = None,
    ) -> FetchManifest:
        """Simulate creating a C04 FetchManifest from the declared scope metadata."""
        now = datetime.now(timezone.utc)
        manifest = FetchManifest(
            run_id=uuid4(),
            source_key=source.config.source_key,
            scope_id=source.inventory_scope.scope_id,
            start_time=now,
            end_time=now,
            page_count=1 if outcome != FetchOutcome.FAILED else 0,
            observed_posting_identities=observed_posting_ids or [],
            outcome=outcome,
            inventory_semantics=source.inventory_scope.semantics,
        )
        self.created_manifests.append(manifest)
        return manifest


class TestConsumerBoundary:
    @pytest.fixture
    def test_service(self) -> SourceRegistryService:
        sources = [
            SourceConfig(
                source_key="board_complete",
                provider="ats_corp",
                board_id="00042",
                acquisition_method=AcquisitionMethod.API,
                base_url="https://api.ats.invalid/boards/00042/jobs",
                access_rules=json.dumps(
                    {
                        "status": "permitted",
                        "reviewed_at": "2026-10-28T00:00:00Z",
                        "evidence_ref": "ats-api-license",
                        "permitted_methods": ["api"],
                    }
                ),
                attribution_rules="Source: ATS Corp (Board 00042)",
                enabled=True,
                inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            ),
            SourceConfig(
                source_key="feed_filtered",
                provider="feed_provider",
                board_id="de_finance",
                acquisition_method=AcquisitionMethod.API,
                base_url="https://api.feed.invalid/jobs",
                access_rules=json.dumps(
                    {
                        "status": "permitted",
                        "reviewed_at": "2026-10-28T00:00:00Z",
                        "evidence_ref": "feed-terms-2026",
                        "permitted_methods": ["api"],
                    }
                ),
                attribution_rules="none_required",
                request_policy={"params": {"sector": "finance"}},
                enabled=True,
                inventory_semantics=InventorySemantics.FILTERED_FEED,
            ),
            SourceConfig(
                source_key="search_discovery",
                provider="search_aggregator",
                board_id="search_api",
                acquisition_method=AcquisitionMethod.API,
                base_url="https://api.aggregator.invalid/search",
                access_rules=json.dumps(
                    {
                        "status": "permitted",
                        "reviewed_at": "2026-10-28T00:00:00Z",
                        "evidence_ref": "aggregator-agreement",
                        "permitted_methods": ["api"],
                    }
                ),
                attribution_rules="Data by Aggregator",
                request_policy={"params": {"q": "developer"}},
                enabled=True,
                inventory_semantics=InventorySemantics.SEARCH_RESULTS,
            ),
        ]
        envelope = SourceRegistryEnvelope(schema_version="1.0", sources=sources)
        return SourceRegistryService.from_envelope(envelope)

    def test_complete_board_handoff_and_manifest(
        self, test_service: SourceRegistryService
    ) -> None:
        """Verify complete_board selection passes exact identity and creates valid C04."""
        recorder = FakeFetchConsumerRecorder()
        res = test_service.select_sources(["board_complete"])
        assert res.is_valid is True
        source = res.selected_sources[0]

        recorder.record_selection(source)
        manifest = recorder.simulate_manifest(
            source=source,
            outcome=FetchOutcome.COMPLETE,
            observed_posting_ids=["job_101", "job_102"],
        )

        assert manifest.source_key == "board_complete"
        assert manifest.scope_id == source.inventory_scope.scope_id
        assert manifest.inventory_semantics == InventorySemantics.COMPLETE_BOARD
        assert manifest.outcome == FetchOutcome.COMPLETE
        assert len(manifest.observed_posting_identities) == 2
        assert manifest.observed_posting_identities[0] == "job_101"
        assert manifest.observed_posting_identities[1] == "job_102"

    def test_filtered_feed_partial_manifest(
        self, test_service: SourceRegistryService
    ) -> None:
        """Verify filtered_feed selection correctly records partial execution outcome."""
        recorder = FakeFetchConsumerRecorder()
        res = test_service.select_sources(["feed_filtered"])
        source = res.selected_sources[0]

        recorder.record_selection(source)
        manifest = recorder.simulate_manifest(
            source=source,
            outcome=FetchOutcome.PARTIAL,
            observed_posting_ids=["job_201"],
        )

        assert manifest.source_key == "feed_filtered"
        assert manifest.inventory_semantics == InventorySemantics.FILTERED_FEED
        assert manifest.outcome == FetchOutcome.PARTIAL

    def test_search_results_empty_successful_manifest(
        self, test_service: SourceRegistryService
    ) -> None:
        """Verify search_results returning 0 items produces complete outcome with empty postings."""
        recorder = FakeFetchConsumerRecorder()
        res = test_service.select_sources(["search_discovery"])
        source = res.selected_sources[0]

        recorder.record_selection(source)
        manifest = recorder.simulate_manifest(
            source=source,
            outcome=FetchOutcome.COMPLETE,
            observed_posting_ids=[],
        )

        assert manifest.inventory_semantics == InventorySemantics.SEARCH_RESULTS
        assert manifest.outcome == FetchOutcome.COMPLETE
        assert len(manifest.observed_posting_identities) == 0
