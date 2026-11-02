"""C02 SearchPolicy contracts.

Defines search criteria independently of candidate history: hard criteria,
preferences, exclusions, missing-information rules, and context strategy selection.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import ContextStrategy


class HardCriterion(ContractModel):
    """Explicit hard filter rule evaluated as pass, fail, or unknown."""

    criterion_id: str = Field(min_length=1, description="Unique identifier for the criterion")
    name: str = Field(min_length=1, description="Human-readable criterion label")
    field: str = Field(min_length=1, description="Target field in the job posting to evaluate")
    operator: str = Field(
        min_length=1,
        description="Evaluation operator (e.g. 'equals', 'contains', 'in', 'gte', 'lte')",
    )
    expected_value: Any = Field(description="Expected value or set for comparison")
    on_missing: Literal["pass", "fail", "unknown"] = Field(
        default="unknown",
        description="Disposition when target field is missing from posting",
    )


class PreferenceRule(ContractModel):
    """Soft preference or ranking booster."""

    rule_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    field: str = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0, description="Relative preference weight (0.0 to 1.0)")
    preferred_values: list[str] = Field(default_factory=list)


class RelevanceConfig(ContractModel):
    """Configuration for broad keyword matching and LLM fit assessment."""

    score_scale: str = Field(
        default="0-100",
        description="Documented scale for relevance scoring",
    )
    min_score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        description="Minimum score for eligible classification (nullable)",
    )
    broad_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords for initial broad semantic candidate recall",
    )
    negative_keywords: list[str] = Field(
        default_factory=list,
        description="Disqualifying keywords proposing rejection",
    )


class SearchPolicy(ContractModel):
    """C02 Search Policy.

    Configures desired job criteria, exclusions, and evaluation behavior
    independently of candidate facts.
    """

    policy_version: str = Field(min_length=1, description="Version of this search policy")
    regions: list[str] = Field(
        default_factory=list,
        description="Target geographic regions / countries (e.g. ['DE'])",
    )
    role_aliases: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping of canonical role names to accepted title aliases",
    )
    skill_aliases: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping of skill names to equivalent keywords",
    )
    hard_criteria: list[HardCriterion] = Field(
        default_factory=list,
        description="List of pass/fail/unknown hard rules",
    )
    preferences: list[PreferenceRule] = Field(
        default_factory=list,
        description="Soft preferences for ranking",
    )
    exclusions: list[str] = Field(
        default_factory=list,
        description="Explicitly excluded company names, keywords, or patterns",
    )
    missing_information_behavior: dict[str, Literal["pass", "fail", "unknown"]] = Field(
        default_factory=dict,
        description="Default disposition when particular criteria fields are missing",
    )
    relevance_configuration: RelevanceConfig = Field(
        default_factory=RelevanceConfig,
        description="Relevance matching configuration",
    )
    primary_context_strategy: ContextStrategy = Field(
        default=ContextStrategy.JSON,
        description="Primary context construction strategy (json or rag)",
    )

