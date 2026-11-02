"""Tests for provider, board, and source key identity preservation (SOURCE-01-S02)."""

from __future__ import annotations

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.errors import ERR_INVALID_IDENTITY
from job_automation.sources.validation import validate_source_config


class TestIdentityPreservation:
    def test_opaque_string_leading_zeros_preserved(self) -> None:
        """Verify leading zeros in board_id ('00042') are preserved as exact string."""
        config = SourceConfig(
            source_key="board_zeros",
            provider="greenhouse",
            board_id="00042",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        effective = validate_source_config(config)
        assert effective.config.board_id == "00042"
        assert effective.inventory_scope.board_id == "00042"

    def test_case_preservation_in_board_and_provider(self) -> None:
        """Verify casing in provider and board_id is preserved exactly."""
        config = SourceConfig(
            source_key="case_test",
            provider="GreenHouse_Global",
            board_id="CorpTenant_EU",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        effective = validate_source_config(config)
        assert effective.config.provider == "GreenHouse_Global"
        assert effective.config.board_id == "CorpTenant_EU"

    def test_whitespace_in_source_key_rejected(self) -> None:
        """Verify internal or padded whitespace in source_key is rejected."""
        config = SourceConfig(
            source_key="bad key with spaces",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        effective = validate_source_config(config)
        assert not effective.is_valid
        assert any(i.code == ERR_INVALID_IDENTITY for i in effective.issues)

    def test_multiple_scopes_can_share_provider_and_board(self) -> None:
        """Verify two distinct source keys can share the same provider and board."""
        cfg_all = SourceConfig(
            source_key="board_a_all",
            provider="fixture_ats",
            board_id="00042",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.fixture-board.invalid/v1/jobs",
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        cfg_finance = SourceConfig(
            source_key="board_a_finance",
            provider="fixture_ats",
            board_id="00042",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.fixture-board.invalid/v1/jobs",
            request_policy={"params": {"dept": "finance"}},
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        )

        eff_all = validate_source_config(cfg_all)
        eff_finance = validate_source_config(cfg_finance)

        # Both valid identity, but different scope IDs
        assert eff_all.config.provider == eff_finance.config.provider
        assert eff_all.config.board_id == eff_finance.config.board_id
        assert eff_all.inventory_scope.scope_id != eff_finance.inventory_scope.scope_id

