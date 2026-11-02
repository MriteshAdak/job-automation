"""Configuration settings for context construction and whole-prompt budgeting."""

from __future__ import annotations

from pydantic import Field

from job_automation.contracts.base import ContractModel


class ContextSettings(ContractModel):
    """Configuration settings for context assembly, mandatory context policy, and token budgeting."""

    mandatory_policy_version: str = Field(
        default="v1",
        description="Version of mandatory context policy rules",
    )
    inclusion_rule_version: str = Field(
        default="v1",
        description="Version of profile inclusion rules",
    )
    builder_version: str = Field(
        default="v1",
        description="Version of the JSON context builder",
    )
    serialization_version: str = Field(
        default="v1",
        description="Version of candidate model projection serialization format",
    )
    default_context_limit: int = Field(
        default=8192,
        gt=0,
        description="Default context window capacity in tokens if not specified in request",
    )
    default_output_reserve: int = Field(
        default=512,
        ge=0,
        description="Default completion output reservation in tokens",
    )
    default_safety_allowance: int = Field(
        default=64,
        ge=0,
        description="Default safety allowance buffer in tokens",
    )
    default_measurement_method: str = Field(
        default="conservative_char_ratio_v1",
        description="Default token measurement or estimation method identifier",
    )
    conservative_chars_per_token: float = Field(
        default=3.5,
        gt=0.0,
        description="Conservative characters-per-token ratio used for heuristic estimation",
    )
    require_exact_measurement: bool = Field(
        default=False,
        description="Whether to reject heuristic estimation when exact tokenizer is unavailable",
    )

