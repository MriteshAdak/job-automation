"""Tests for generation settings allowlist and numeric validation (LLM-01-S03)."""

from __future__ import annotations

import math

import pytest

from job_automation.contracts.errors import ErrorCategory
from job_automation.models.settings import validate_generation_settings


class TestSettings:
    def test_valid_settings_deep_copied(self) -> None:
        raw = {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 40,
            "seed": 42,
            "repeat_penalty": 1.1,
            "stop": ["\n\n", "User:"],
        }
        validated, err = validate_generation_settings(raw)
        assert err is None
        assert validated == raw
        # Verify deep copy
        raw["stop"].append("System:")
        assert "System:" not in validated["stop"]

    @pytest.mark.parametrize(
        "invalid_key",
        ["tools", "tool_choice", "remote_model", "endpoint", "url", "arbitrary_plugin"],
    )
    def test_unauthorized_keys_rejected(self, invalid_key: str) -> None:
        raw = {invalid_key: "value"}
        validated, err = validate_generation_settings(raw)
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "unauthorized generation setting" in err.message

    @pytest.mark.parametrize(
        "non_finite",
        [float("nan"), float("inf"), float("-inf")],
    )
    def test_non_finite_numbers_rejected(self, non_finite: float) -> None:
        raw = {"temperature": non_finite}
        validated, err = validate_generation_settings(raw)
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "must be finite" in err.message

    def test_temperature_out_of_range(self) -> None:
        raw = {"temperature": 2.5}
        validated, err = validate_generation_settings(raw)
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "in [0.0, 2.0]" in err.message

    def test_top_p_out_of_range(self) -> None:
        raw = {"top_p": 0.0}
        validated, err = validate_generation_settings(raw)
        assert err is not None
        assert err.category == ErrorCategory.VALIDATION
        assert "in (0.0, 1.0]" in err.message
