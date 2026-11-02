"""Configuration loaders and policy resolvers for AUTO-02."""

from __future__ import annotations

import json
from pathlib import Path

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.generation.automatic.records import (
    AutomaticDraftPolicy,
    AutomaticVolumeLimits,
    DocumentVariantConfig,
    RepeatPolicy,
)


def load_automatic_draft_policy(
    policy_path: Path | str,
) -> tuple[AutomaticDraftPolicy | None, ClassifiedError | None]:
    """Load and validate an AutomaticDraftPolicy from a JSON configuration file.

    If file does not exist or JSON is invalid, returns a ClassifiedError.
    """
    path = Path(policy_path)
    if not path.is_file():
        err = ClassifiedError.from_category(
            category=ErrorCategory.CONFIGURATION,
            message=f"Automatic draft policy file not found: {path}",
            details={"policy_path": str(path), "reason_code": "policy_file_not_found"},
        )
        return None, err

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        policy = AutomaticDraftPolicy.model_validate(data)
        return policy, None
    except Exception as exc:
        err = ClassifiedError.from_category(
            category=ErrorCategory.CONFIGURATION,
            message=f"Failed to parse automatic draft policy from {path}: {exc}",
            details={"policy_path": str(path), "reason_code": "policy_validation_failed"},
        )
        return None, err

