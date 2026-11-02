"""Adapter binding to checked source selections (SOURCE-02-S02).

Enforces:
- Verification of checked selection from SOURCE-01
- Enabled and permitted access status checks
- Match between declared adapter capability and source acquisition method
- Verification that config supplied to fetch_page matches the bound source
"""

from __future__ import annotations

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.sources.models import AccessReviewStatus, EffectiveSource


def validate_adapter_binding(
    source: EffectiveSource,
    supported_method: AcquisitionMethod,
    adapter_name: str,
) -> None:
    """Validate that an EffectiveSource can be bound to an adapter.

    Raises:
        ValueError if the source is disabled, unreviewed/denied, or method is mismatched.
    """
    if not source.config.enabled:
        raise ValueError(
            f"Cannot bind adapter '{adapter_name}': source '{source.config.source_key}' is disabled"
        )

    if source.access_review.status != AccessReviewStatus.PERMITTED:
        raise ValueError(
            f"Cannot bind adapter '{adapter_name}': source '{source.config.source_key}' "
            f"access is '{source.access_review.status.value}', must be 'permitted'"
        )

    if source.config.acquisition_method != supported_method:
        raise ValueError(
            f"Cannot bind adapter '{adapter_name}' (requires {supported_method.value}): "
            f"source '{source.config.source_key}' has method '{source.config.acquisition_method.value}'"
        )


def verify_runtime_config(bound_source: EffectiveSource, supplied_config: SourceConfig) -> None:
    """Verify that the SourceConfig passed to fetch_page matches the bound EffectiveSource."""
    if supplied_config.source_key != bound_source.config.source_key:
        raise ValueError(
            f"Supplied SourceConfig key '{supplied_config.source_key}' does not match "
            f"bound adapter source key '{bound_source.config.source_key}'"
        )
    if supplied_config.provider != bound_source.config.provider:
        raise ValueError(
            f"Supplied provider '{supplied_config.provider}' does not match "
            f"bound provider '{bound_source.config.provider}'"
        )
    if supplied_config.board_id != bound_source.config.board_id:
        raise ValueError(
            f"Supplied board_id '{supplied_config.board_id}' does not match "
            f"bound board_id '{bound_source.config.board_id}'"
        )

