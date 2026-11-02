"""Configuration models and defaults for generation worker execution (GEN-01-S08)."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.generation.request_mapping import RequestFieldMapping


class GenerationLimits(ContractModel):
    """Execution and polling bounds per worker cycle."""

    max_requests_per_cycle: int = Field(default=20, ge=1, le=100)
    max_pages_per_cycle: int = Field(default=10, ge=1, le=50)
    page_size: int = Field(default=20, ge=1, le=100)


class GenerationStaleness(ContractModel):
    """Staleness evaluation thresholds for remote running requests."""

    stale_running_minutes: float = Field(default=30.0, ge=1.0)
    clock_skew_minutes: float = Field(default=2.0, ge=0.0)


class GenerationRetryPolicy(ContractModel):
    """Retry limits and exponential backoff configuration."""

    max_stage_attempts: int = Field(default=5, ge=1, le=20)
    initial_backoff_seconds: float = Field(default=30.0, ge=1.0)
    max_backoff_seconds: float = Field(default=900.0, ge=1.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)


class GenerationSettings(ContractModel):
    """Aggregate configuration for the generation worker."""

    schema_version: str = Field(default="1.0")
    limits: GenerationLimits = Field(default_factory=GenerationLimits)
    staleness: GenerationStaleness = Field(default_factory=GenerationStaleness)
    retry: GenerationRetryPolicy = Field(default_factory=GenerationRetryPolicy)
    mapping: RequestFieldMapping = Field(default_factory=RequestFieldMapping)
    required_formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    watch_poll_interval_seconds: float = Field(default=60.0, ge=1.0)


def load_generation_settings(path: str | Path | None = None) -> GenerationSettings:
    """Load generation settings from a JSON file, or return safe defaults if not provided."""
    if path is None:
        return GenerationSettings()

    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Generation settings file not found: {p}")

    content = p.read_text(encoding="utf-8")
    return GenerationSettings.model_validate_json(content)

