"""High-level service interface for loading, validating, and fingerprinting search policies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_automation.configuration import load_config
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.policy.loader import load_policy_dict
from job_automation.policy.models import PolicyValidationResult
from job_automation.policy.validation import validate_policy_dict


class PolicyService:
    """Service facade for search policy operations."""

    @classmethod
    def load_and_validate(cls, policy_path: str | Path) -> PolicyValidationResult:
        """Load a policy from an explicit filesystem path and validate it."""
        path = Path(policy_path)
        data, explicit_missing, load_issues, err = load_policy_dict(path)
        if err is not None or data is None:
            return PolicyValidationResult(
                is_valid=False,
                effective_policy=None,
                fingerprint=None,
                issues=load_issues,
            )

        res = validate_policy_dict(data, explicit_missing)
        # Combine load issues (e.g. warnings) with validation issues
        all_issues = load_issues + res.issues
        all_issues.sort(key=lambda i: (i.field_path, i.code, i.severity))
        return PolicyValidationResult(
            is_valid=res.is_valid and not any(i.severity == "error" for i in load_issues),
            effective_policy=res.effective_policy if res.is_valid else None,
            fingerprint=res.fingerprint if res.is_valid else None,
            issues=all_issues,
        )

    @classmethod
    def load_from_config(
        cls,
        config_path: str | Path | None = None,
        data_root_override: str | Path | None = None,
    ) -> PolicyValidationResult:
        """Resolve active policy from application configuration and validate it."""
        try:
            config, paths = load_config(
                config_path=config_path,
                data_root_override=data_root_override,
            )
        except Exception as exc:
            return PolicyValidationResult(
                is_valid=False,
                effective_policy=None,
                fingerprint=None,
                issues=[
                    ValidationIssue(
                        field_path="config",
                        code="config_resolution_failed",
                        message=f"Failed to load application configuration: {exc}",
                        severity="error",
                    )
                ],
            )

        if not paths.policy_path:
            return PolicyValidationResult(
                is_valid=False,
                effective_policy=None,
                fingerprint=None,
                issues=[
                    ValidationIssue(
                        field_path="active_policy_ref",
                        code="missing_active_policy_reference",
                        message="Configuration contains no active_policy_ref setting",
                        severity="error",
                    )
                ],
            )

        return cls.load_and_validate(paths.policy_path)

