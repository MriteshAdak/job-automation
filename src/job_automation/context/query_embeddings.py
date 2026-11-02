"""Generation and compatibility verification of requirement query embeddings."""

from __future__ import annotations

import math
import uuid
from typing import Sequence

from job_automation.context.errors import (
    RetrievalChannelError,
    RetrievalIncompatibleError,
)
from job_automation.context.selector_records import RequirementQuerySet
from job_automation.contracts.interfaces import ModelProvider
from job_automation.contracts.retrieval_index import EmbeddingConfiguration


class QueryEmbeddingCoordinator:
    """Coordinates local embedding model invocation for requirement queries with strict validation."""

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    def embed_queries(
        self,
        query_set: RequirementQuerySet,
        embedding_config: EmbeddingConfiguration,
        normalize: bool = True,
    ) -> tuple[dict[str, list[float]], list[uuid.UUID]]:
        """Embed queries with query prefix, verify dimension/digest, and apply unit normalization."""
        if not query_set.queries:
            return {}, []

        prefixed_texts: list[str] = [
            f"{embedding_config.query_prefix}{q.query_text}"
            for q in query_set.queries
        ]

        resp, err = self.provider.embed(
            texts=prefixed_texts,
            model=embedding_config.model_identifier,
        )
        if err is not None:
            raise RetrievalChannelError(
                f"Query embedding generation failed: {err.message}",
                field_path="model_identifier",
                details={"error": err.message, "model": embedding_config.model_identifier},
            )
        if resp is None:
            raise RetrievalChannelError(
                "Query embedding provider returned null response without error",
                field_path="model_identifier",
            )

        # Dimension verification
        if resp.dimension != embedding_config.dimension:
            raise RetrievalIncompatibleError(
                f"Query embedding dimension {resp.dimension} does not match expected {embedding_config.dimension}",
                field_path="dimension",
                details={"expected": embedding_config.dimension, "actual": resp.dimension},
            )

        # Model digest verification if declared
        if embedding_config.model_digest is not None and resp.model_digest is not None:
            if resp.model_digest != embedding_config.model_digest:
                raise RetrievalIncompatibleError(
                    f"Query embedding model digest '{resp.model_digest}' does not match expected '{embedding_config.model_digest}'",
                    field_path="model_digest",
                    details={
                        "expected": embedding_config.model_digest,
                        "actual": resp.model_digest,
                    },
                )

        if len(resp.vectors) != len(query_set.queries):
            raise RetrievalChannelError(
                f"Expected {len(query_set.queries)} query vectors, got {len(resp.vectors)}",
                field_path="vectors",
            )

        call_ids: list[uuid.UUID] = []
        if resp.call_id is not None:
            call_ids.append(resp.call_id)

        query_vectors: dict[str, list[float]] = {}
        for q, raw_vec in zip(query_set.queries, resp.vectors):
            if len(raw_vec) != embedding_config.dimension:
                raise RetrievalIncompatibleError(
                    f"Vector length {len(raw_vec)} does not match dimension {embedding_config.dimension}",
                    field_path="dimension",
                )

            # Check for non-finite values
            for val in raw_vec:
                if math.isnan(val) or math.isinf(val):
                    raise RetrievalChannelError(
                        "Embedding provider returned NaN or Inf in vector",
                        field_path="vectors",
                    )

            # Apply unit normalization if configured
            if normalize:
                norm = math.sqrt(sum(v * v for v in raw_vec))
                if norm == 0.0:
                    raise RetrievalChannelError(
                        "Embedding provider returned all-zero vector",
                        field_path="vectors",
                    )
                normalized_vec = [v / norm for v in raw_vec]
            else:
                normalized_vec = list(raw_vec)

            query_vectors[q.query_id] = normalized_vec

        return query_vectors, call_ids
