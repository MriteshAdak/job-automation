"""Service protocols and ports for CONTEXT-01 context construction."""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.context.records import (
    JsonContextRequest,
    MeasurementResult,
    RenderedPrompt,
    WholePromptMeasurement,
)
from job_automation.contracts.context import ContextBundle
from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.postings import NormalizedPosting


@runtime_checkable
class JobBindingPort(Protocol):
    """Port for validating job content association with the declared revision."""

    def validate_binding(
        self,
        canonical_job_id: uuid.UUID,
        posting_revision: str,
        posting: NormalizedPosting,
    ) -> None:
        """Validate that the given posting content corresponds to the canonical job and revision.

        Raises JobBindingError on validation failure.
        """
        ...


@runtime_checkable
class TokenCounterPort(Protocol):
    """Port for measuring or estimating token consumption."""

    def count_tokens(self, text: str) -> MeasurementResult:
        """Count or estimate tokens in a text string."""
        ...

    def count_rendered_prompt(self, rendered: RenderedPrompt) -> WholePromptMeasurement:
        """Measure total tokens P and component breakdown for the rendered prompt."""
        ...


@runtime_checkable
class PromptRendererPort(Protocol):
    """Port for rendering instructions, schema, job, and candidate JSON into a prompt."""

    def render(
        self,
        request: JsonContextRequest,
        candidate_json: str,
    ) -> RenderedPrompt:
        """Render complete prompt and components."""
        ...


@runtime_checkable
class JsonContextBuilderPort(Protocol):
    """Port for full JSON ContextBundle construction."""

    def build(
        self,
        request: JsonContextRequest,
    ) -> tuple[ContextBundle | None, ClassifiedError | None]:
        """Construct full JSON ContextBundle or return ClassifiedError."""
        ...

