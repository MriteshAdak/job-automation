"""Exact-term keyword retrieval for CONTEXT-04 hybrid RAG."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Sequence

from job_automation.context.index_ports import IndexHandlePort
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector_records import (
    RequirementQuery,
    RequirementQuerySet,
    RetrievalHit,
)


class KeywordRetriever:
    """Retrieves and scores evidence chunks based on distinct matching query terms."""

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self.settings = settings or RetrievalSettings()

    def retrieve(
        self,
        query_set: RequirementQuerySet,
        index_handle: IndexHandlePort,
    ) -> list[RetrievalHit]:
        """Perform exact-term search for each query and produce ranked RetrievalHit records."""
        all_hits: list[RetrievalHit] = []

        if index_handle.row_count == 0 or not query_set.queries:
            return all_hits

        for query in query_set.queries:
            if not query.terms:
                continue

            # Lookup term postings in bulk
            postings_map = index_handle.lookup_terms(query.terms)

            # Map row_ordinal -> set of distinct matching normalized terms
            row_to_matching_terms: dict[int, set[str]] = defaultdict(set)
            for term, postings in postings_map.items():
                for posting in postings:
                    row_to_matching_terms[posting.row_ordinal].add(term)

            # Score each matching row by count of distinct terms
            # Group by primary_fact_id: collapse duplicate chunks for same primary fact
            # Best chunk keeps the highest term count
            fact_best_chunk: dict[uuid.UUID, tuple[int, int, uuid.UUID]] = {}
            # tuple: (score, -row_ordinal, chunk_id)

            for row_ordinal, matching_terms in row_to_matching_terms.items():
                score = len(matching_terms)
                if score <= 0:
                    continue

                chunk = index_handle.get_chunk(row_ordinal)
                primary_id = chunk.primary_fact_id
                entry = (score, -row_ordinal, chunk.chunk_id)

                if primary_id not in fact_best_chunk or entry > fact_best_chunk[primary_id]:
                    fact_best_chunk[primary_id] = entry

            # Sort primary facts descending by score, tie-break by row_ordinal (lowest first), chunk_id, fact_id
            sorted_facts = sorted(
                fact_best_chunk.items(),
                key=lambda item: (
                    -item[1][0],       # score descending
                    -item[1][1],       # row_ordinal ascending (since item[1][1] is -row_ordinal)
                    str(item[1][2]),   # chunk_id ascending
                    str(item[0]),      # fact_id ascending
                ),
            )

            # Cap at per_channel_limit
            bounded_facts = sorted_facts[: self.settings.per_channel_limit]

            for rank_idx, (fact_id, (score, neg_row, chunk_id)) in enumerate(bounded_facts, start=1):
                all_hits.append(
                    RetrievalHit(
                        chunk_id=chunk_id,
                        fact_id=fact_id,
                        channel="keyword",
                        score=float(score),
                        rank=rank_idx,
                        query_id=query.query_id,
                    )
                )

        return all_hits

