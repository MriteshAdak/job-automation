"""Tests for inventory semantics validation (SOURCE-01-S05)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import ERR_SCOPE_CONTRADICTION
from job_automation.sources.inventory import validate_inventory_scope
from job_automation.sources.request_policy import validate_request_policy


class TestInventorySemanticsValidation:
    def test_complete_board_rejects_query_filter_contradictions(self) -> None:
        """Verify complete_board with search/filter queries produces ERR_SCOPE_CONTRADICTION."""
        config = SourceConfig(
            source_key="contradictory_board",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"q": "developer", "city": "Munich"}},
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        policy, _ = validate_request_policy(config)
        _, issues = validate_inventory_scope(config, policy)
        assert any(i.code == ERR_SCOPE_CONTRADICTION for i in issues)

    def test_complete_board_without_filters_passes(self) -> None:
        """Verify clean complete_board without restrictive filters validates successfully."""
        config = SourceConfig(
            source_key="clean_board",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout_seconds": 30.0},
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        policy, _ = validate_request_policy(config)
        scope, issues = validate_inventory_scope(config, policy)
        assert len(issues) == 0
        assert scope.semantics == InventorySemantics.COMPLETE_BOARD

    def test_filtered_feed_permits_filters(self) -> None:
        """Verify filtered_feed permits department/category filters."""
        config = SourceConfig(
            source_key="dept_feed",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"department": "engineering"}},
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )
        policy, _ = validate_request_policy(config)
        scope, issues = validate_inventory_scope(config, policy)
        assert len(issues) == 0
        assert scope.semantics == InventorySemantics.FILTERED_FEED

    def test_search_results_permits_search_queries(self) -> None:
        """Verify search_results permits freeform query parameters."""
        config = SourceConfig(
            source_key="search_res",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"q": "python developer", "country": "DE"}},
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
        )
        policy, _ = validate_request_policy(config)
        scope, issues = validate_inventory_scope(config, policy)
        assert len(issues) == 0
        assert scope.semantics == InventorySemantics.SEARCH_RESULTS

