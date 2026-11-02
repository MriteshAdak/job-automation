"""Tests for token measurement, estimation, and distinguishing exact from approximate counts."""

from __future__ import annotations

import pytest

from job_automation.context.errors import MeasurementError
from job_automation.context.measurement import (
    ConservativeCharRatioEstimator,
    ExactTokenCounter,
)
from job_automation.context.records import RenderedPrompt


class TestTokenMeasurement:
    def test_conservative_char_ratio_estimator(self) -> None:
        estimator = ConservativeCharRatioEstimator(chars_per_token=4.0)

        res = estimator.count_tokens("12345678")
        assert res.token_count == 2
        assert res.is_exact is False
        assert res.method == "conservative_char_ratio_v1"

        # Ceiling behavior: 9 chars / 4.0 = 2.25 -> 3 tokens
        res_ceil = estimator.count_tokens("123456789")
        assert res_ceil.token_count == 3

    def test_whole_prompt_measurement_with_estimator(self) -> None:
        estimator = ConservativeCharRatioEstimator(chars_per_token=4.0)
        rendered = RenderedPrompt(
            full_prompt="A" * 400,
            instruction_text="B" * 80,
            job_text="C" * 120,
            requirements_text="D" * 40,
            output_schema_text="",
            candidate_json="E" * 120,
            framing_text="F" * 40,
        )

        measurement = estimator.count_rendered_prompt(rendered)

        assert measurement.is_exact is False
        assert measurement.total_input_tokens == 100
        assert measurement.instruction_tokens == 20
        assert measurement.job_tokens == 40  # (120 + 40) / 4 = 40
        assert measurement.candidate_tokens == 30  # 120 / 4 = 30
        assert measurement.framing_tokens == 10

    def test_exact_token_counter(self) -> None:
        # Simple whitespace tokenizer for test
        def whitespace_tokenizer(text: str) -> int:
            return len(text.split())

        counter = ExactTokenCounter(tokenize_fn=whitespace_tokenizer)

        res = counter.count_tokens("five words in this sentence")
        assert res.token_count == 5
        assert res.is_exact is True
        assert res.method == "exact_tokenizer_v1"

    def test_exact_counter_rejects_negative_counts(self) -> None:
        def bad_tokenizer(text: str) -> int:
            return -5

        counter = ExactTokenCounter(tokenize_fn=bad_tokenizer)
        with pytest.raises(MeasurementError, match="negative count"):
            counter.count_tokens("some text")

    def test_invalid_chars_per_token_rejected(self) -> None:
        with pytest.raises(MeasurementError, match="must be positive"):
            ConservativeCharRatioEstimator(chars_per_token=0.0)

