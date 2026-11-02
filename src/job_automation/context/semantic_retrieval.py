"""Dense vector semantic retrieval for CONTEXT-04 hybrid RAG."""

from __future__ import annotations

import math
import uuid
from typing import Sequence

from job_automation.context.index_ports import IndexHandlePort
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector_records import (
    RequirementQuerySet,
    RetrievalHit,
)


class SemanticRetriever:
    """Retrieves and scores evidence chunks based on cosine similarity of normalized vectors."""

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self.settings = settings or RetrievalSettings()

    def retrieve(
        self,
        query_set: RequirementQuerySet,
        query_vectors: dict[str, list[float]],
        index_handle: IndexHandlePort,
    ) -> list[RetrievalHit]:
        """Perform vector similarity search for each query and produce ranked RetrievalHit records."""
        all_hits: list[RetrievalHit] = []

        if index_handle.row_count == 0 or not query_set.queries:
            return all_hits

        # Read all chunk vectors from index
        chunk_vectors = index_handle.get_vectors()

        for query in query_set.queries:
            query_vector = query_vectors.get(query.query_id)
            if not query_vector:
                continue

            # Group hits by primary_fact_id: collapse duplicate chunks for same primary fact
            # Best chunk keeps the highest similarity score
            fact_best_chunk: dict[uuid.UUID, tuple[float, int, uuid.UUID]] = {}
            # tuple: (similarity, -row_ordinal, chunk_id)

            for row_ordinal, chunk_vec in enumerate(chunk_vectors):
                # Both query and index vectors are L2-normalized unit vectors
                similarity = sum(q * c for q, c in zip(query_vector, chunk_vec))

                if math.isnan(similarity) or math.isinf(similarity):
                    continue

                if (
                    self.settings.semantic_threshold is not None
                    and similarity < self.settings.semantic_threshold
                ):
                    continue

                chunk = index_handle.get_chunk(row_ordinal)
                primary_id = chunk.primary_fact_id
                entry = (similarity, -row_ordinal, chunk.chunk_id)

                if primary_id not in fact_best_chunk or entry > fact_best_chunk[primary_id]:
                    fact_best_chunk[primary_id] = entry

            # Sort primary facts descending by similarity, tie-break by row_ordinal (lowest first), chunk_id, fact_id
            sorted_facts = sorted(
                fact_best_chunk.items(),
                key=lambda item: (
                    -item[1][0],       # similarity descending
                    -item[1][1],       # row_ordinal ascending (since item[1][1] is -row_ordinal)
                    str(item[1][2]),   # chunk_id ascending
                    str(item[0]),      # fact_id ascending
                ),
            )

            # Cap at per_channel_limit
            bounded_facts = sorted_facts[: self.settings.per_channel_limit]

            for rank_idx, (fact_id, (sim, neg_row, chunk_id)) in enumerate(bounded_facts, start=1):
                all_hits.append(
                    RetrievalHit(
                        chunk_id=chunk_id,
                        fact_id=fact_id,
                        channel="semantic",
                        score=float(sim),
                        rank=rank_idx,
                        query_id=query.query_id,
                    )
                )

        return all_hits

