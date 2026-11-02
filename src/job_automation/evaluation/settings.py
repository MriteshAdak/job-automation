"""Evaluation configuration, constants, and proposed targets (EVAL-01-S01).

Enforces:
- Pinned evaluation schema version and metric specification version.
- Strict isolation defaults (dedicated eval database name, eval workspace).
- Explicit rejection of publication overrides or Salesforce gateway usage.
- All benchmark quality targets are explicitly marked PROPOSED, not measured facts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal
from pydantic import Field, field_validator, model_validator

from job_automation.contracts.base import ContractModel
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.models.configuration import validate_loopback_url


EVAL_SCHEMA_VERSION: str = "1.0"
METRIC_SPEC_VERSION: str = "v1.0"
DEFAULT_EVAL_DB_NAME: str = "evaluation.db"
DEFAULT_EVAL_WORKSPACE_DIR: str = "evaluation"
DEFAULT_ORDER_SEED: int = 42

# Phase 1 extensions (GEN-02 through GEN-06) status
PHASE1_EXTENSIONS_STATUS: str = "DEFERRED"


class EvaluationSettings(ContractModel):
    """Configuration for local evaluation runs and benchmarks."""

    schema_version: str = Field(default=EVAL_SCHEMA_VERSION, min_length=1)
    metric_spec_version: str = Field(default=METRIC_SPEC_VERSION, min_length=1)
    
    # Absolute path to runtime data root or evaluation workspace root
    eval_root: str = Field(
        description="Absolute path to runtime evaluation directory (isolated from production DB)",
    )
    
    # Model configuration (must bind to loopback)
    model_service_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Local model service URL; must bind strictly to loopback",
    )
    model_identifier: str = Field(
        default="local-assessor",
        min_length=1,
        description="Target local model identifier",
    )
    model_digest: str = Field(
        default="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        min_length=7,
        description="Immutable sha256 model digest",
    )
    effective_decoding_settings: dict[str, Any] = Field(
        default_factory=lambda: {"temperature": 0.0, "seed": 42},
        description="Decoding parameters pinned for reproducible comparison",
    )
    prompt_version: str = Field(default="v1", min_length=1)
    
    # Resource budgets
    context_limit: int = Field(default=8192, gt=0)
    output_reserve: int = Field(default=1024, ge=0)
    safety_allowance: int = Field(default=64, ge=0)
    
    # Execution options
    order_randomization_seed: int = Field(default=DEFAULT_ORDER_SEED)
    repetitions_per_pair: int = Field(default=1, ge=1)
    extractor_mode: Literal["deterministic", "llm"] = Field(default="deterministic")
    extractor_version: str = Field(default="v1-deterministic")
    
    # Optional production DB path for read-only sampling
    production_db_path: str | None = Field(
        default=None,
        description="Optional absolute path to production DB for read-only rejected-job sampling",
    )
    
    # Strict boundary checks: publication configuration is FORBIDDEN
    enable_sync: bool = Field(
        default=False,
        description="Publication toggle. MUST be False; publication from evaluation is forbidden.",
    )
    
    @field_validator("model_service_url")
    @classmethod
    def _validate_loopback(cls, v: str) -> str:
        return validate_loopback_url(v)

    @field_validator("eval_root")
    @classmethod
    def _validate_absolute_root(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            raise ValueError(f"eval_root must be an absolute path, got '{v}'")
        return str(p)

    @model_validator(mode="after")
    def _validate_no_publication(self) -> EvaluationSettings:
        if self.enable_sync:
            raise ValueError(
                "enable_sync=True is strictly forbidden in evaluation. "
                "Accidental publication from evaluation is prevented by contract."
            )
        return self


# Explicit proposed targets - these are engineering targets to validate against, NOT claimed facts.
PROPOSED_TARGETS: dict[str, Any] = {
    "target_status": "PROPOSED",
    "notes": "Engineering aspirations for German white-collar matching; not user-validated facts or guaranteed metrics.",
    "targets": {
        "max_false_negative_rate": 0.05,
        "min_retrieval_coverage": 0.80,
        "min_admitted_evidence_coverage": 0.90,
        "max_unsupported_claim_rate": 0.02,
        "max_case_latency_ms": 30000.0,
    },
}

