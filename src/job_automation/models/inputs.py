"""Input binding and in-memory input resolution (LLM-01-S01, S03).

Provides explicit immutable input registration keyed by call_id.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

from job_automation.models.fingerprints import (
    compute_embedding_fingerprint,
    compute_generation_fingerprint,
)
from job_automation.models.records import (
    BoundEmbeddingInput,
    BoundGenerationInput,
)


class InMemoryInputResolver:
    """Thread-safe in-memory input resolver for caller-prepared prompts and texts."""

    def __init__(self) -> None:
        self._generation_inputs: dict[uuid.UUID, BoundGenerationInput] = {}
        self._embedding_inputs: dict[uuid.UUID, BoundEmbeddingInput] = {}

    def bind_generation(
        self,
        call_id: uuid.UUID,
        prompt: str,
        system_prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> BoundGenerationInput:
        """Bind an immutable generation input to a call_id."""
        fingerprint = compute_generation_fingerprint(prompt, system_prompt)
        bound = BoundGenerationInput(
            call_id=call_id,
            prompt=prompt,
            system_prompt=system_prompt,
            input_fingerprint=fingerprint,
            metadata=copy.deepcopy(metadata or {}),
        )
        self._generation_inputs[call_id] = bound
        return bound

    def bind_embedding(
        self,
        call_id: uuid.UUID,
        texts: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> BoundEmbeddingInput:
        """Bind an immutable embedding input to a call_id."""
        fingerprint = compute_embedding_fingerprint(texts)
        bound = BoundEmbeddingInput(
            call_id=call_id,
            texts=list(texts),
            input_fingerprint=fingerprint,
            metadata=copy.deepcopy(metadata or {}),
        )
        self._embedding_inputs[call_id] = bound
        return bound

    def resolve_generation_input(self, call_id: uuid.UUID) -> BoundGenerationInput | None:
        """Look up bound generation input for the specified call_id."""
        return self._generation_inputs.get(call_id)

    def resolve_embedding_input(self, call_id: uuid.UUID) -> BoundEmbeddingInput | None:
        """Look up bound embedding input for the specified call_id."""
        return self._embedding_inputs.get(call_id)

