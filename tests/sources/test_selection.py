"""Tests for source selection behavior and preflight gates (SOURCE-01-S06)."""

from __future__ import annotations

import json

import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.models import SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService


@pytest.fixture
def sample_service() -> SourceRegistryService:
    """Fixture providing a test SourceRegistryService with diverse readiness states."""
    sources = [
        # 1. Valid, permitted, enabled
        SourceConfig(
            source_key="src_valid_enabled",
            provider="prov_a",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.a.invalid/jobs",
            access_rules=json.dumps(
                {
                    "status": "permitted",
                    "reviewed_at": "2026-10-28T00:00:00Z",
                    "evidence_ref": "terms-v1",
                    "permitted_methods": ["api"],
                }
            ),
            attribution_rules="Source: Provider A",
            enabled=True,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        ),
        # 2. Valid, permitted, disabled
        SourceConfig(
            source_key="src_valid_disabled",
            provider="prov_b",
            board_id="b2",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.b.invalid/jobs",
            access_rules=json.dumps(
                {
                    "status": "permitted",
                    "reviewed_at": "2026-10-28T00:00:00Z",
                    "evidence_ref": "terms-v2",
                    "permitted_methods": ["api"],
                }
            ),
            attribution_rules="none_required",
            enabled=False,
            inventory_semantics=InventorySemantics.FILTERED_FEED,
        ),
        # 3. Enabled, but unreviewed access
        SourceConfig(
            source_key="src_unreviewed_access",
            provider="prov_c",
            board_id="b3",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.c.invalid/jobs",
            access_rules="prose notes only; not structured",
            attribution_rules="none_required",
            enabled=True,
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
        ),
        # 4. Enabled, but unknown attribution
        SourceConfig(
            source_key="src_unknown_attrib",
            provider="prov_d",
            board_id="b4",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.d.invalid/jobs",
            access_rules=json.dumps(
                {
                    "status": "permitted",
                    "reviewed_at": "2026-10-28T00:00:00Z",
                    "evidence_ref": "terms-v4",
                    "permitted_methods": ["api"],
                }
            ),
            attribution_rules=None,
            enabled=True,
            inventory_semantics=InventorySemantics.SEARCH_RESULTS,
        ),
    ]
    envelope = SourceRegistryEnvelope(schema_version="1.0", sources=sources)
    return SourceRegistryService.from_envelope(envelope)


class TestSourceSelection:
    def test_select_valid_enabled_source(self, sample_service: SourceRegistryService) -> None:
        """Verify selecting a valid, permitted, enabled source succeeds."""
        res = sample_service.select_sources(["src_valid_enabled"])
        assert res.is_valid is True
        assert len(res.blockers) == 0
        assert len(res.selected_sources) == 1
        assert res.selected_sources[0].config.source_key == "src_valid_enabled"

    def test_select_disabled_source_fails(self, sample_service: SourceRegistryService) -> None:
        """Verify selecting a disabled source fails and returns zero executable sources."""
        res = sample_service.select_sources(["src_valid_disabled"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("disabled" in b for b in res.blockers)

    def test_select_unconfigured_source_fails(self, sample_service: SourceRegistryService) -> None:
        """Verify selecting an unknown source key fails with missing configuration blocker."""
        res = sample_service.select_sources(["nonexistent_key"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("not configured" in b for b in res.blockers)

    def test_select_unreviewed_access_source_fails(
        self, sample_service: SourceRegistryService
    ) -> None:
        """Verify selecting a source with unreviewed access fails."""
        res = sample_service.select_sources(["src_unreviewed_access"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("lacks approved access" in b for b in res.blockers)

    def test_select_unknown_attribution_source_fails(
        self, sample_service: SourceRegistryService
    ) -> None:
        """Verify selecting a source with unknown attribution fails."""
        res = sample_service.select_sources(["src_unknown_attrib"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("unknown attribution" in b for b in res.blockers)

    def test_empty_selection_is_valid(self, sample_service: SourceRegistryService) -> None:
        """Verify an explicit empty selection succeeds with 0 selected sources."""
        res = sample_service.select_sources([])
        assert res.is_valid is True
        assert len(res.selected_sources) == 0
        assert len(res.blockers) == 0

    def test_mixed_selection_fails_atomically(
        self, sample_service: SourceRegistryService
    ) -> None:
        """Verify if one source is valid and one is blocked, the entire selection fails atomically."""
        res = sample_service.select_sources(["src_valid_enabled", "src_valid_disabled"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("disabled" in b for b in res.blockers)

    def test_duplicate_selection_fails(self, sample_service: SourceRegistryService) -> None:
        """Verify duplicate keys in requested selection are rejected."""
        res = sample_service.select_sources(["src_valid_enabled", "src_valid_enabled"])
        assert res.is_valid is False
        assert len(res.selected_sources) == 0
        assert any("Duplicate" in b for b in res.blockers)

    def test_selection_returns_detached_snapshot(
        self, sample_service: SourceRegistryService
    ) -> None:
        """Verify mutations to returned selection cannot alter registered service state."""
        res = sample_service.select_sources(["src_valid_enabled"])
        assert res.is_valid is True
        selected = res.selected_sources[0]

        # Verify registry entry in service is untouched
        reg_source = sample_service.get_source("src_valid_enabled")
        assert reg_source is not None
        assert reg_source.config.source_key == selected.config.source_key
        assert reg_source is not selected  # distinct object instance

