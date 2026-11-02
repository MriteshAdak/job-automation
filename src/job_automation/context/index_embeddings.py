"""Embedding coordination and batch validation through LLM-01 ModelProvider."""

from __future__ import annotations

import math
import uuid
from typing import Sequence

from job_automation.context.index_errors import (
    IndexCapacityError,
    IndexIncompatibleError,
    IndexValidationError,
)
from job_automation.context.index_model_audit import IndexAuditSink
from job_automation.contracts.evidence_chunks import EvidenceChunk
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexSettings,
)


def _l2_normalize(vector: Sequence[float], metric: str) -> list[float]:
    """Compute L2 normalized vector or raise if zero vector under cosine metric."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        if metric == "cosine":
            raise IndexValidationError(
                "Zero vector encountered with cosine metric; normalization undefined",
                field_path="vector",
            )
        return list(vector)
    return [float(x / norm) for x in vector]


class IndexEmbeddingCoordinator:
    """Coordinates batching, prefix application, provider invocation, and vector validation."""

    def __init__(
        self,
        provider: ModelProvider,
        config: EmbeddingConfiguration,
        settings: IndexSettings,
        audit_sink: IndexAuditSink | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.settings = settings
        self.audit_sink = audit_sink or IndexAuditSink()

    def embed_chunks(
        self,
        chunks: Sequence[EvidenceChunk],
    ) -> tuple[list[list[float]], list[uuid.UUID], int]:
        """Obtain validated, normalized vectors for target evidence chunks.

        Returns:
        - vectors: Ordered list of float32 vectors aligned 1:1 with input chunks
        - call_ids: List of call IDs from provider calls
        - total_input_bytes: Sum of raw UTF-8 input text bytes embedded
        """
        if not chunks:
            return [], [], 0

        # Apply document prefix
        texts = [f"{self.config.document_prefix}{c.retrieval_text}" for c in chunks]
        total_input_bytes = sum(len(t.encode("utf-8")) for t in texts)

        # Partition into batches respecting max_batch_items and max_batch_bytes
        batches: list[list[str]] = []
        current_batch: list[str] = []
        current_batch_bytes = 0

        for text in texts:
            text_byte_len = len(text.encode("utf-8"))
            if text_byte_len > self.config.max_batch_bytes:
                raise IndexCapacityError(
                    f"Single text length ({text_byte_len} bytes) exceeds max_batch_bytes ({self.config.max_batch_bytes})",
                    field_path="retrieval_text",
                    details={"bytes": text_byte_len, "max_batch_bytes": self.config.max_batch_bytes},
                )

            if current_batch and (
                len(current_batch) >= self.config.max_batch_items
                or (current_batch_bytes + text_byte_len) > self.config.max_batch_bytes
            ):
                batches.append(current_batch)
                current_batch = []
                current_batch_bytes = 0

            current_batch.append(text)
            current_batch_bytes += text_byte_len

        if current_batch:
            batches.append(current_batch)

        # Execute batches sequentially through provider
        all_vectors: list[list[float]] = []
        all_call_ids: list[uuid.UUID] = []

        for batch in batches:
            resp, err = self.provider.embed(batch, model=self.config.model_identifier)
            if err is not None:
                raise IndexIncompatibleError(
                    f"ModelProvider embedding failed: {err.message}",
                    field_path="model_provider.embed",
                    details=err.details,
                )

            if resp is None:
                raise IndexIncompatibleError(
                    "ModelProvider returned null embedding response",
                    field_path="model_provider.embed",
                )

            # Validate returned metadata
            if resp.dimension != self.config.dimension:
                raise IndexIncompatibleError(
                    f"Model dimension mismatch: returned {resp.dimension}, expected {self.config.dimension}",
                    field_path="resp.dimension",
                    details={"observed": resp.dimension, "expected": self.config.dimension},
                )

            if resp.model_identifier != self.config.model_identifier:
                raise IndexIncompatibleError(
                    f"Model identifier mismatch: returned '{resp.model_identifier}', expected '{self.config.model_identifier}'",
                    field_path="resp.model_identifier",
                    details={"observed": resp.model_identifier, "expected": self.config.model_identifier},
                )

            if (
                self.config.model_digest is not None
                and resp.model_digest is not None
                and resp.model_digest != self.config.model_digest
            ):
                raise IndexIncompatibleError(
                    f"Model digest mismatch: returned '{resp.model_digest}', expected '{self.config.model_digest}'",
                    field_path="resp.model_digest",
                    details={"observed": resp.model_digest, "expected": self.config.model_digest},
                )

            if len(resp.vectors) != len(batch):
                raise IndexValidationError(
                    f"Model returned {len(resp.vectors)} vectors for batch of {len(batch)} items",
                    field_path="resp.vectors",
                )

            # Validate and normalize each vector
            for vec in resp.vectors:
                if len(vec) != self.config.dimension:
                    raise IndexValidationError(
                        f"Vector element count {len(vec)} != dimension {self.config.dimension}",
                        field_path="vector",
                    )

                for elem in vec:
                    if isinstance(elem, bool) or not isinstance(elem, (int, float)):
                        raise IndexValidationError(
                            f"Invalid non-float vector element: {type(elem)}",
                            field_path="vector.element",
                        )
                    if math.isnan(elem) or math.isinf(elem):
                        raise IndexValidationError(
                            "Non-finite float element (NaN or Inf) encountered in vector",
                            field_path="vector.element",
                        )

                if self.settings.normalization == "l2":
                    normed = _l2_normalize(vec, self.settings.metric)
                else:
                    normed = [float(x) for x in vec]

                all_vectors.append(normed)

            if resp.call_id is not None:
                all_call_ids.append(resp.call_id)
                self.audit_sink.record_call(
                    call_id=resp.call_id,
                    model_identifier=resp.model_identifier,
                    model_digest=resp.model_digest,
                    dimension=resp.dimension,
                    item_count=len(batch),
                    duration_ms=0.0,
                    token_usage=resp.token_usage,
                )

        return all_vectors, all_call_ids, total_input_bytes

