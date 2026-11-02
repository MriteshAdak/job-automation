"""Fake token counter for deterministic boundary testing of whole-prompt budgeting."""

from __future__ import annotations

from typing import Callable

from job_automation.context.ports import TokenCounterPort
from job_automation.context.records import (
    MeasurementResult,
    RenderedPrompt,
    WholePromptMeasurement,
)


class FakeTokenCounter(TokenCounterPort):
    """Test fake providing controlled token counts for arithmetic and boundary testing."""

    def __init__(
        self,
        fixed_total: int | None = None,
        candidate_tokens: int = 500,
        instruction_tokens: int = 100,
        job_tokens: int = 300,
        framing_tokens: int = 50,
        is_exact: bool = True,
        method_name: str = "fake_test_counter",
        custom_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.fixed_total = fixed_total
        self.candidate_tokens = candidate_tokens
        self.instruction_tokens = instruction_tokens
        self.job_tokens = job_tokens
        self.framing_tokens = framing_tokens
        self.is_exact = is_exact
        self.method_name = method_name
        self.custom_counter = custom_counter

    def count_tokens(self, text: str) -> MeasurementResult:
        if self.custom_counter is not None:
            count = self.custom_counter(text)
        elif self.fixed_total is not None:
            count = self.fixed_total
        else:
            count = len(text.split())
        return MeasurementResult(
            token_count=count,
            is_exact=self.is_exact,
            method=self.method_name,
            version="test-1.0",
        )

    def count_rendered_prompt(self, rendered: RenderedPrompt) -> WholePromptMeasurement:
        if self.custom_counter is not None:
            total = self.custom_counter(rendered.full_prompt)
            cand = self.custom_counter(rendered.candidate_json)
            inst = self.custom_counter(rendered.instruction_text)
            job = self.custom_counter(rendered.job_text + rendered.requirements_text + rendered.output_schema_text)
            framing = self.custom_counter(rendered.framing_text)
        elif self.fixed_total is not None:
            total = self.fixed_total
            cand = self.candidate_tokens
            inst = self.instruction_tokens
            job = self.job_tokens
            framing = self.framing_tokens
        else:
            # Word-count based simulation
            total = len(rendered.full_prompt.split())
            cand = len(rendered.candidate_json.split())
            inst = len(rendered.instruction_text.split())
            job = len((rendered.job_text + rendered.requirements_text + rendered.output_schema_text).split())
            framing = len(rendered.framing_text.split())

        return WholePromptMeasurement(
            total_input_tokens=total,
            candidate_tokens=cand,
            instruction_tokens=inst,
            job_tokens=job,
            framing_tokens=framing,
            is_exact=self.is_exact,
            method=self.method_name,
            version="test-1.0",
        )

