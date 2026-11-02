"""Tests for deterministic scope identity derivation (SOURCE-01-S05)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.inventory import validate_inventory_scope
from job_automation.sources.request_policy import validate_request_policy


class TestScopeIdentity:
    def test_scope_id_format(self) -> None:
        """Verify scope_id follows tagged format: scope-v1:sha256:<64 hex chars>."""
        config = SourceConfig(
            source_key="fmt_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        policy, _ = validate_request_policy(config)
        scope, _ = validate_inventory_scope(config, policy)
        assert scope.scope_id.startswith("scope-v1:sha256:")
        digest = scope.scope_id.split(":")[-1]
        assert len(digest) == 64
        int(digest, 16)  # must be valid hex

    def test_scope_id_invariant_to_transport_and_timeout(self) -> None:
        """Verify scope_id does not change when timeout, max_attempts, or headers change."""
        cfg1 = SourceConfig(
            source_key="src1",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"timeout_seconds": 15.0, "max_attempts": 1},
        )
        cfg2 = SourceConfig(
            source_key="src1",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={
                "timeout_seconds": 60.0,
                "max_attempts": 5,
                "headers": {"User-Agent": "DifferentAgent/2.0"},
            },
        )

        p1, _ = validate_request_policy(cfg1)
        p2, _ = validate_request_policy(cfg2)
        s1, _ = validate_inventory_scope(cfg1, p1)
        s2, _ = validate_inventory_scope(cfg2, p2)

        assert s1.scope_id == s2.scope_id

    def test_scope_id_invariant_to_pagination_cursor(self) -> None:
        """Verify scope_id does not change when page, offset, or cursor params are present."""
        cfg_base = SourceConfig(
            source_key="src_page",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs?category=it",
        )
        cfg_paged = SourceConfig(
            source_key="src_page",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs?category=it&page=3&cursor=xyz123&offset=50",
        )

        p1, _ = validate_request_policy(cfg_base)
        p2, _ = validate_request_policy(cfg_paged)
        s1, _ = validate_inventory_scope(cfg_base, p1)
        s2, _ = validate_inventory_scope(cfg_paged, p2)

        assert s1.scope_id == s2.scope_id

    def test_scope_id_sensitive_to_query_filter_change(self) -> None:
        """Verify scope_id changes when category or query parameters change."""
        cfg_berlin = SourceConfig(
            source_key="src_berlin",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"city": "Berlin"}},
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )
        cfg_munich = SourceConfig(
            source_key="src_munich",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            request_policy={"params": {"city": "Munich"}},
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )

        p1, _ = validate_request_policy(cfg_berlin)
        p2, _ = validate_request_policy(cfg_munich)
        s1, _ = validate_inventory_scope(cfg_berlin, p1)
        s2, _ = validate_inventory_scope(cfg_munich, p2)

        assert s1.scope_id != s2.scope_id

    def test_scope_id_sensitive_to_semantics_change(self) -> None:
        """Verify scope_id changes between filtered_feed and search_results."""
        cfg_feed = SourceConfig(
            source_key="src_feed",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )
        cfg_search = SourceConfig(
            source_key="src_search",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
        )

        p1, _ = validate_request_policy(cfg_feed)
        p2, _ = validate_request_policy(cfg_search)
        s1, _ = validate_inventory_scope(cfg_feed, p1)
        s2, _ = validate_inventory_scope(cfg_search, p2)

        assert s1.scope_id != s2.scope_id

