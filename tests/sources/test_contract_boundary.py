"""Tests for C03 contract boundary, models, and immutability (SOURCE-01-S01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
    SourceRegistryEnvelope,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "contracts" / "C03"


class TestC03ContractBoundary:
    def test_existing_c03_valid_fixture(self) -> None:
        """Verify the existing C03 valid fixture validates without errors."""
        fixture_file = FIXTURES_DIR / "valid.json"
        data = json.loads(fixture_file.read_text(encoding="utf-8"))

        config = SourceConfig.model_validate(data)
        assert config.source_key == "arbeitnow_de"
        assert config.provider == "arbeitnow"
        assert config.board_id == "default"
        assert config.acquisition_method == AcquisitionMethod.API
        assert config.base_url == "https://job-board-api.com/api/v1/jobs"
        assert config.enabled is False
        assert config.inventory_semantics == InventorySemantics.FILTERED_FEED
        assert config.request_policy == {"timeout": 30}

    def test_existing_c03_invalid_fixture(self) -> None:
        """Verify the existing C03 invalid fixture fails validation."""
        fixture_file = FIXTURES_DIR / "invalid.json"
        data = json.loads(fixture_file.read_text(encoding="utf-8"))

        with pytest.raises(ValidationError):
            SourceConfig.model_validate(data)

    def test_c03_forbids_extra_fields(self) -> None:
        """Verify C03 model strictly forbids unknown extra fields."""
        data = {
            "schema_version": "1.0",
            "source_key": "test_src",
            "provider": "test_prov",
            "board_id": "test_board",
            "acquisition_method": "api",
            "base_url": "https://api.test.invalid/jobs",
            "unknown_extra_field": "forbidden",
        }
        with pytest.raises(ValidationError) as exc_info:
            SourceConfig.model_validate(data)
        assert "extra_forbidden" in str(exc_info.value)

    def test_c03_is_frozen(self) -> None:
        """Verify SourceConfig is frozen and immutable."""
        config = SourceConfig(
            source_key="frozen_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        with pytest.raises(ValidationError):
            config.enabled = True  # type: ignore[misc]

    def test_registry_envelope_model(self) -> None:
        """Verify SourceRegistryEnvelope validates C03 records and schema_version."""
        config = SourceConfig(
            source_key="envelope_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        envelope = SourceRegistryEnvelope(
            schema_version="1.0",
            sources=[config],
        )
        assert len(envelope.sources) == 1
        assert envelope.sources[0].source_key == "envelope_test"

    def test_effective_source_structure(self) -> None:
        """Verify EffectiveSource holds C03 config and typed domain models."""
        config = SourceConfig(
            source_key="eff_test",
            provider="prov",
            board_id="b1",
            acquisition_method=AcquisitionMethod.API,
            base_url="https://api.test.invalid/jobs",
        )
        effective = EffectiveSource(
            config=config,
            access_review=AccessReview(status=AccessReviewStatus.PERMITTED, evidence_ref="ref-1"),
            attribution_review=AttributionReview(status=AttributionStatus.REQUIRED, notice="Notice"),
            request_policy=EffectiveRequestPolicy(timeout_seconds=20.0),
            inventory_scope=InventoryScope(
                scope_id="scope-v1:sha256:abcd",
                semantics=InventorySemantics.COMPLETE_BOARD,
                provider="prov",
                board_id="b1",
                acquisition_method=AcquisitionMethod.API,
                base_url="https://api.test.invalid/jobs",
            ),
            is_valid=True,
            is_runnable=False,
        )
        assert effective.config.source_key == "eff_test"
        assert effective.access_review.status == AccessReviewStatus.PERMITTED
        assert effective.inventory_scope.semantics == InventorySemantics.COMPLETE_BOARD

