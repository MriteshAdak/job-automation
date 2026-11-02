"""Reciprocal Rank Fusion (RRF) and candidate aggregation for CONTEXT-04."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Sequence

from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector_records import (
    FusedCandidate,
    RetrievalHit,
)


class ReciprocalRankFuser:
    """Deterministically fuses keyword and semantic retrieval channels using RRF."""

    def __init__(self, settings: RetrievalSettings | None = None) -> None:
        self.settings = settings or RetrievalSettings()

    def fuse(
        self,
        hits: Sequence[RetrievalHit],
    ) -> list[FusedCandidate]:
        """Fuse channel hits per query, aggregate across queries, and sort candidates deterministically."""
        if not hits:
            return []

        # Group hits by (query_id, fact_id)
        query_fact_hits: dict[str, dict[uuid.UUID, list[RetrievalHit]]] = defaultdict(
            lambda: defaultdict(list)
        )
        fact_all_hits: dict[uuid.UUID, list[RetrievalHit]] = defaultdict(list)

        for hit in hits:
            query_fact_hits[hit.query_id][hit.fact_id].append(hit)
            fact_all_hits[hit.fact_id].append(hit)

        # Compute per-query RRF scores:
        # S_q(fact) = sum_{hit} (1.0 / (rrf_k + hit.rank))
        fact_query_scores: dict[uuid.UUID, dict[str, float]] = defaultdict(dict)
        for query_id, fact_map in query_fact_hits.items():
            for fact_id, fact_hits in fact_map.items():
                score = 0.0
                for hit in fact_hits:
                    score += 1.0 / (self.settings.rrf_k + hit.rank)
                fact_query_scores[fact_id][query_id] = score

        # Aggregate across queries according to multi_query_aggregation setting (default 'max')
        fused_candidates: list[FusedCandidate] = []
        for fact_id, q_scores in fact_query_scores.items():
            if self.settings.multi_query_aggregation == "sum":
                agg_score = sum(q_scores.values())
            else:  # max (default)
                agg_score = max(q_scores.values())

            all_hits_for_fact = fact_all_hits[fact_id]
            best_rank = min(h.rank for h in all_hits_for_fact)
            query_count = len(q_scores)

            fused_candidates.append(
                FusedCandidate(
                    fact_id=fact_id,
                    fused_score=agg_score,
                    channel_hits=all_hits_for_fact,
                    query_count=query_count,
                    best_channel_rank=best_rank,
                    selection_reason="fused_score",
                    is_admitted=False,
                    omission_reason=None,
                )
            )

        # Stable deterministic tie-break sorting:
        # 1. fused_score descending
        # 2. query_count descending
        # 3. best_channel_rank ascending
        # 4. str(fact_id) ascending (lexicographical string UUID)
        sorted_candidates = sorted(
            fused_candidates,
            key=lambda c: (
                -c.fused_score,
                -c.query_count,
                c.best_channel_rank,
                str(c.fact_id),
            ),
        )

        return sorted_candidates

