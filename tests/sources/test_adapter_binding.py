"""Tests for adapter binding to checked source selections (SOURCE-02-S02)."""

from __future__ import annotations

import json
import pytest

from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.adapters.binding import (
    validate_adapter_binding,
    verify_runtime_config,
)
from job_automation.sources.models import (
    AccessReview,
    AccessReviewStatus,
    AttributionReview,
    AttributionStatus,
    EffectiveRequestPolicy,
    EffectiveSource,
    InventoryScope,
)


@pytest.fixture
def valid_manual_effective_source() -> EffectiveSource:
    config = SourceConfig(
        source_key="manual_inbox",
        provider="manual",
        board_id="inbox_01",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="manual://inbox",
        access_rules=json.dumps(
            {
                "status": "permitted",
                "reviewed_at": "2026-10-28T00:00:00Z",
                "evidence_ref": "operator-input",
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
            evidence_ref="operator-input",
            permitted_methods=[AcquisitionMethod.MANUAL_IMPORT],
        ),
        attribution_review=AttributionReview(status=AttributionStatus.NONE_REQUIRED),
        request_policy=EffectiveRequestPolicy(),
        inventory_scope=InventoryScope(
            scope_id="scope-v1:manual_test",
            semantics=InventorySemantics.SEARCH_RESULTS,
            provider="manual",
            board_id="inbox_01",
            acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
            base_url="manual://inbox",
        ),
    )


def test_validate_adapter_binding_success(valid_manual_effective_source: EffectiveSource) -> None:
    # Should not raise
    validate_adapter_binding(
        valid_manual_effective_source,
        supported_method=AcquisitionMethod.MANUAL_IMPORT,
        adapter_name="manual_text",
    )


def test_validate_adapter_binding_disabled(valid_manual_effective_source: EffectiveSource) -> None:
    disabled_config = valid_manual_effective_source.config.model_copy(update={"enabled": False})
    disabled_source = valid_manual_effective_source.model_copy(update={"config": disabled_config})
    with pytest.raises(ValueError, match="is disabled"):
        validate_adapter_binding(
            disabled_source,
            supported_method=AcquisitionMethod.MANUAL_IMPORT,
            adapter_name="manual_text",
        )


def test_validate_adapter_binding_unreviewed(valid_manual_effective_source: EffectiveSource) -> None:
    unreviewed_review = valid_manual_effective_source.access_review.model_copy(
        update={"status": AccessReviewStatus.UNREVIEWED}
    )
    unreviewed_source = valid_manual_effective_source.model_copy(update={"access_review": unreviewed_review})
    with pytest.raises(ValueError, match="must be 'permitted'"):
        validate_adapter_binding(
            unreviewed_source,
            supported_method=AcquisitionMethod.MANUAL_IMPORT,
            adapter_name="manual_text",
        )


def test_validate_adapter_binding_method_mismatch(valid_manual_effective_source: EffectiveSource) -> None:
    with pytest.raises(ValueError, match="requires api"):
        validate_adapter_binding(
            valid_manual_effective_source,
            supported_method=AcquisitionMethod.API,
            adapter_name="api_adapter",
        )


def test_verify_runtime_config(valid_manual_effective_source: EffectiveSource) -> None:
    # Matching config
    verify_runtime_config(valid_manual_effective_source, valid_manual_effective_source.config)

    # Mismatched source key
    wrong_key_config = valid_manual_effective_source.config.model_copy(update={"source_key": "wrong_key"})
    with pytest.raises(ValueError, match="does not match bound adapter source key"):
        verify_runtime_config(valid_manual_effective_source, wrong_key_config)

    # Mismatched provider
    wrong_prov_config = valid_manual_effective_source.config.model_copy(update={"provider": "other_prov"})
    with pytest.raises(ValueError, match="does not match bound provider"):
        verify_runtime_config(valid_manual_effective_source, wrong_prov_config)
