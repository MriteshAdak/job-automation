"""Run settings and configuration loading for pipeline execution (RUN-01)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import Field

from job_automation.contracts.base import ContractModel
from job_automation.contracts.enums import ContextStrategy
from job_automation.orchestration.records import AssessmentMode


class RunSettings(ContractModel):
    """Execution options for a pipeline run."""

    schema_version: str = Field(default="1.0", description="Settings schema version")
    assessment_mode: AssessmentMode = Field(
        default=AssessmentMode.RULES,
        description="Assessment mode: rules or llm",
    )
    primary_strategy: ContextStrategy = Field(
        default=ContextStrategy.JSON,
        description="Context strategy for LLM assessment: json or rag",
    )
    max_requests_per_source: int = Field(
        default=50,
        ge=1,
        description="Maximum HTTP requests per source during discovery",
    )
    max_pages_per_source: int = Field(
        default=10,
        ge=1,
        description="Maximum pages per source during discovery",
    )
    sync_enabled: bool = Field(
        default=True,
        description="Whether to execute Salesforce sync planning and dispatch",
    )
    sync_max_operations: int = Field(
        default=100,
        ge=1,
        description="Maximum outbox write steps to dispatch in one run",
    )
    sync_max_reconciliations: int = Field(
        default=50,
        ge=1,
        description="Maximum uncertain steps to reconcile in one run",
    )
    candidate_backup_enabled: bool = Field(
        default=True,
        description="Whether to run candidate fields backup scan",
    )
    backup_batch_size: int = Field(
        default=50,
        ge=1,
        description="Maximum candidate records to backup in one scan",
    )
    lock_timeout_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Seconds to wait for worker lock before raising LockContentionError (0.0 = fail immediately)",
    )

    def compute_fingerprint(self) -> str:
        """Compute deterministic SHA-256 fingerprint of run settings."""
        serialized = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def load_from_file(cls, path: str | Path) -> RunSettings:
        """Load RunSettings from a JSON file."""
        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Run settings file '{path}' not found")
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        return cls.model_validate(data)

