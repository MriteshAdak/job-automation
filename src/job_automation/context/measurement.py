"""Token counting and whole-prompt measurement implementations for CONTEXT-01.

Provides:
- ConservativeCharRatioEstimator: Explicitly labeled approximate token estimator.
- ExactTokenCounter: Deterministic exact tokenizer wrapper.
- Distinguishes measured counts from estimates in all records.
"""

from __future__ import annotations

import math
from typing import Callable

from job_automation.context.errors import MeasurementError
from job_automation.context.ports import TokenCounterPort
from job_automation.context.records import (
    MeasurementResult,
    RenderedPrompt,
    WholePromptMeasurement,
)


class ConservativeCharRatioEstimator(TokenCounterPort):
    """Heuristic token estimator using a conservative characters-per-token ratio.

    Explicitly labeled with is_exact=False.
    Applies ceiling to character divisions to prevent undercounting.
    """

    def __init__(
        self,
        chars_per_token: float = 3.5,
        version: str = "1.0",
        method_name: str = "conservative_char_ratio_v1",
    ) -> None:
        if chars_per_token <= 0:
            raise MeasurementError("chars_per_token must be positive")
        self.chars_per_token = chars_per_token
        self.version = version
        self.method_name = method_name

    def count_tokens(self, text: str) -> MeasurementResult:
        if not text:
            return MeasurementResult(
                token_count=0,
                is_exact=False,
                method=self.method_name,
                version=self.version,
            )
        count = math.ceil(len(text) / self.chars_per_token)
        return MeasurementResult(
            token_count=count,
            is_exact=False,
            method=self.method_name,
            version=self.version,
        )

    def count_rendered_prompt(self, rendered: RenderedPrompt) -> WholePromptMeasurement:
        total_count = math.ceil(len(rendered.full_prompt) / self.chars_per_token)
        cand_count = math.ceil(len(rendered.candidate_json) / self.chars_per_token)
        inst_count = math.ceil(len(rendered.instruction_text) / self.chars_per_token)
        job_count = math.ceil(
            (len(rendered.job_text) + len(rendered.requirements_text) + len(rendered.output_schema_text))
            / self.chars_per_token
        )
        framing_count = math.ceil(len(rendered.framing_text) / self.chars_per_token)

        return WholePromptMeasurement(
            total_input_tokens=total_count,
            candidate_tokens=cand_count,
            instruction_tokens=inst_count,
            job_tokens=job_count,
            framing_tokens=framing_count,
            is_exact=False,
            method=self.method_name,
            version=self.version,
        )


class ExactTokenCounter(TokenCounterPort):
    """Token counter backed by an exact tokenizer callback."""

    def __init__(
        self,
        tokenize_fn: Callable[[str], int],
        version: str = "1.0",
        method_name: str = "exact_tokenizer_v1",
    ) -> None:
        self._tokenize_fn = tokenize_fn
        self.version = version
        self.method_name = method_name

    def count_tokens(self, text: str) -> MeasurementResult:
        if not text:
            return MeasurementResult(
                token_count=0,
                is_exact=True,
                method=self.method_name,
                version=self.version,
            )
        count = self._tokenize_fn(text)
        if count < 0:
            raise MeasurementError(f"Tokenizer returned negative count: {count}")
        return MeasurementResult(
            token_count=count,
            is_exact=True,
            method=self.method_name,
            version=self.version,
        )

    def count_rendered_prompt(self, rendered: RenderedPrompt) -> WholePromptMeasurement:
        total = self._tokenize_fn(rendered.full_prompt)
        cand = self._tokenize_fn(rendered.candidate_json)
        inst = self._tokenize_fn(rendered.instruction_text)
        job = self._tokenize_fn(
            rendered.job_text + rendered.requirements_text + rendered.output_schema_text
        )
        framing = self._tokenize_fn(rendered.framing_text)

        if total < 0 or cand < 0 or inst < 0 or job < 0 or framing < 0:
            raise MeasurementError("Tokenizer returned negative component count")

        return WholePromptMeasurement(
            total_input_tokens=total,
            candidate_tokens=cand,
            instruction_tokens=inst,
            job_tokens=job,
            framing_tokens=framing,
            is_exact=True,
            method=self.method_name,
            version=self.version,
        )

