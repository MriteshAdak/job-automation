"""Port interfaces and protocol definitions for GEN-05 rendering service."""
from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from job_automation.generation.render_records import LocalRenderResult
from job_automation.generation.validation_records import ValidatedDraftForRendering


@runtime_checkable
class DocumentRendererServicePort(Protocol):
    """Port interface for rendering drafts or reopening saved artifact sets."""

    def render_or_reopen(
        self,
        validated_draft: ValidatedDraftForRendering,
        requested_formats: list[str] | None = None,
    ) -> LocalRenderResult:
        """Render a validated draft or reopen existing immutable saved artifacts."""
        ...

    def reopen_artifact_set(
        self,
        request_id: uuid.UUID,
    ) -> LocalRenderResult:
        """Reopen and verify all saved artifacts for a request without re-rendering."""
        ...

