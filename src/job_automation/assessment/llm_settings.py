"""Configuration and version settings for model-assisted assessment (MATCH-02)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel


class LLMAssessmentSettings(ContractModel):
    """Configuration settings and prompt/schema versions for LLM assessment."""

    schema_version: str = Field(default="1.0", description="Contract schema version")
    prompt_version: str = Field(default="v1", description="Assessment prompt version")
    system_instruction_version: str = Field(default="v1", description="System prompt version")
    extraction_prompt_version: str = Field(default="v1", description="Requirement extraction prompt version")
    extraction_schema_version: str = Field(default="1.0", description="Requirement extraction schema version")
    composer_version: str = Field(default="v1", description="C11 composition logic version")

    # Scale & threshold
    score_scale: str = Field(default="0-100", description="Declared score scale")
    min_score_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Minimum score required for eligibility if configured",
    )

    # Resource bounds
    max_requirements: int = Field(default=20, ge=1, le=50)
    default_context_limit: int = Field(default=8192, gt=0)
    default_output_reserve: int = Field(default=1024, ge=0)
    default_safety_allowance: int = Field(default=64, ge=0)
    max_passage_chars: int = Field(default=500, gt=0)

    # Defaults
    model_identifier: str = Field(default="local-assessor")

    def compute_settings_fingerprint(self) -> str:
        """Compute stable SHA-256 fingerprint of output-affecting settings."""
        data = {
            "schema_version": self.schema_version,
            "prompt_version": self.prompt_version,
            "system_instruction_version": self.system_instruction_version,
            "extraction_prompt_version": self.extraction_prompt_version,
            "composer_version": self.composer_version,
            "score_scale": self.score_scale,
            "min_score_threshold": self.min_score_threshold,
            "max_requirements": self.max_requirements,
            "default_context_limit": self.default_context_limit,
            "default_output_reserve": self.default_output_reserve,
            "default_safety_allowance": self.default_safety_allowance,
            "model_identifier": self.model_identifier,
        }
        canonical_bytes = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical_bytes).hexdigest()}"


DEFAULT_LLM_ASSESSMENT_SETTINGS = LLMAssessmentSettings()

