"""Deterministic fake embedding provider for reproducible unit and integration testing."""

from __future__ import annotations

import hashlib
import math
import struct
import uuid
from typing import Sequence

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import EmbeddingResponse, ModelProvider
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage


class DeterministicFakeEmbeddingProvider(ModelProvider):
    """Generates reproducible float32 vectors without network or GPU execution."""

    def __init__(
        self,
        model_identifier: str = "fake-embedder",
        dimension: int = 8,
        model_digest: str | None = "fake-digest-v1",
        injected_error: ClassifiedError | None = None,
    ) -> None:
        self.model_identifier = model_identifier
        self.dimension = dimension
        self.model_digest = model_digest
        self.injected_error = injected_error
        self.calls: list[list[str]] = []

    def generate(self, call: ModelCall) -> ModelResult:
        raise NotImplementedError("Fake provider is configured for embeddings only")

    def embed(
        self,
        texts: list[str],
        model: str,
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        self.calls.append(list(texts))

        if self.injected_error is not None:
            return None, self.injected_error

        vectors: list[list[float]] = []
        for text in texts:
            vec = self._vector_from_text(text, self.dimension)
            vectors.append(vec)

        resp = EmbeddingResponse(
            vectors=vectors,
            model_identifier=self.model_identifier,
            dimension=self.dimension,
            model_digest=self.model_digest,
            call_id=uuid.uuid4(),
            token_usage=TokenUsage(prompt_tokens=len(texts) * 10, completion_tokens=0, total_tokens=len(texts) * 10),
        )
        return resp, None

    @staticmethod
    def _vector_from_text(text: str, dimension: int) -> list[float]:
        """Derive normalized, non-zero float vector deterministically from text."""
        raw_vals: list[float] = []
        for d in range(dimension):
            h = hashlib.sha256(f"{d}:{text}".encode("utf-8")).digest()
            val = struct.unpack("<f", h[:4])[0]
            if math.isnan(val) or math.isinf(val):
                val = 1.0
            raw_vals.append(val)

        # Ensure vector is non-zero
        norm = math.sqrt(sum(v * v for v in raw_vals))
        if norm == 0.0:
            raw_vals[0] = 1.0
            norm = 1.0

        return [v / norm for v in raw_vals]
