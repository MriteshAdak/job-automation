"""Model settings validation and allowlist enforcement (LLM-01-S03).

Prevents execution of arbitrary tools, shell authority, remote endpoints,
or non-finite parameters through generation_settings.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory

ALLOWED_GENERATION_SETTINGS: frozenset[str] = frozenset(
    {
        "temperature",
        "top_p",
        "top_k",
        "seed",
        "repeat_penalty",
        "presence_penalty",
        "frequency_penalty",
        "stop",
        "max_tokens",
        "num_predict",
    }
)


def validate_generation_settings(
    raw_settings: dict[str, Any],
) -> tuple[dict[str, Any], ClassifiedError | None]:
    """Validate generation settings against typed allowlist.

    Returns (validated_copy, error).
    """
    if not isinstance(raw_settings, dict):
        return {}, ClassifiedError.from_category(
            ErrorCategory.VALIDATION,
            "generation_settings must be a dictionary",
        )

    validated: dict[str, Any] = {}

    for key, value in raw_settings.items():
        if key not in ALLOWED_GENERATION_SETTINGS:
            return {}, ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Unknown or unauthorized generation setting '{key}'",
                field_path=f"generation_settings.{key}",
                details={"unsupported_key": key},
            )

        # Validate numeric finite values
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    f"Setting '{key}' must be finite, got '{value}'",
                    field_path=f"generation_settings.{key}",
                )

        # Specific type and range checks
        if key == "temperature":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0 or value > 2.0:
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    "temperature must be a finite float in [0.0, 2.0]",
                    field_path="generation_settings.temperature",
                )
            validated[key] = float(value)

        elif key == "top_p":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0.0 or value > 1.0:
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    "top_p must be a finite float in (0.0, 1.0]",
                    field_path="generation_settings.top_p",
                )
            validated[key] = float(value)

        elif key == "top_k":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    "top_k must be a non-negative integer",
                    field_path="generation_settings.top_k",
                )
            validated[key] = int(value)

        elif key == "seed":
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    "seed must be an integer or None",
                    field_path="generation_settings.seed",
                )
            validated[key] = value

        elif key in {"repeat_penalty", "presence_penalty", "frequency_penalty"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    f"{key} must be a numeric float",
                    field_path=f"generation_settings.{key}",
                )
            validated[key] = float(value)

        elif key == "stop":
            if value is not None:
                if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
                    return {}, ClassifiedError.from_category(
                        ErrorCategory.VALIDATION,
                        "stop must be a list of strings or None",
                        field_path="generation_settings.stop",
                    )
                validated[key] = list(value)
            else:
                validated[key] = None

        elif key in {"max_tokens", "num_predict"}:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                return {}, ClassifiedError.from_category(
                    ErrorCategory.VALIDATION,
                    f"{key} must be a positive integer",
                    field_path=f"generation_settings.{key}",
                )
            validated[key] = int(value)

    return copy.deepcopy(validated), None

