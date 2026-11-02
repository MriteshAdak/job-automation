"""Typed GEN-03 composition and consumer boundaries; no runtime management API."""
from __future__ import annotations

import uuid
from typing import Protocol

from job_automation.contracts.models import ModelCall
from job_automation.generation.draft_records import DraftGenerationResult
from job_automation.generation.input_records import FrozenContextRecipe, FrozenGenerationOptions, FrozenJobSnapshot
from job_automation.contracts.generation import GenerationRequest


class DraftIdentityVerifier(Protocol):
    def __call__(self, call: ModelCall) -> tuple[str, str] | None:
        """Trusted invocation-bound identity check; MODEL-01 supplies the implementation."""
        ...


class FrozenRecipeProvider(Protocol):
    def configure(self, request: GenerationRequest, job: FrozenJobSnapshot,
                  options: FrozenGenerationOptions, context_recipe: FrozenContextRecipe
                  ) -> tuple[FrozenGenerationOptions, FrozenContextRecipe]: ...


class DraftContentServicePort(Protocol):
    def generate_content(self, request_id: uuid.UUID) -> DraftGenerationResult: ...
    def reopen_draft(self, receipt_id: uuid.UUID) -> DraftGenerationResult: ...
