"""C03 SourceConfig contracts.

Defines source registry configuration, permitted access policies, attribution rules,
and inventory completeness semantics.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import AcquisitionMethod, InventorySemantics


class SourceConfig(ContractModel):
    """C03 Source Configuration.

    Configures permitted acquisition methods, rate/access policies, and inventory semantics
    for each job provider board or feed.
    """

    source_key: str = Field(
        min_length=1,
        description="Unique identifier for this configured source (e.g. 'arbeitnow_de')",
    )
    provider: str = Field(
        min_length=1,
        description="Provider platform name (e.g. 'arbeitnow', 'greenhouse', 'manual')",
    )
    board_id: str = Field(
        min_length=1,
        description="Board or tenant identifier within the provider",
    )
    acquisition_method: AcquisitionMethod = Field(
        description="Acquisition mechanism: api, permitted_scraping, manual_import",
    )
    base_url: str = Field(
        min_length=1,
        description="Base URL or entry endpoint for fetching",
    )
    access_rules: str | None = Field(
        default=None,
        description="Documented access constraints, permitted paths, or rate limits",
    )
    attribution_rules: str | None = Field(
        default=None,
        description="Required attribution or licensing notices",
    )
    request_policy: dict[str, Any] = Field(
        default_factory=dict,
        description="HTTP request policies: headers, parameters, timeout seconds",
    )
    enabled: bool = Field(
        default=False,
        description="Whether this source is currently active (synthetic examples default disabled)",
    )
    inventory_semantics: InventorySemantics = Field(
        default=InventorySemantics.SEARCH_RESULTS,
        description="Inventory scope: complete_board, filtered_feed, or search_results",
    )

