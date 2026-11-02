"""Tests for reciprocal rank fusion and hybrid candidate scoring (S04, RET-04, RET-05, RET-13)."""

from __future__ import annotations

import uuid
import pytest

from job_automation.context.fusion import ReciprocalRankFuser
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector_records import RetrievalHit


def test_rrf_both_channels_boost() -> None:
    """A fact appearing in both channels receives score = 1/(60+r1) + 1/(60+r2)."""
    fuser = ReciprocalRankFuser(settings=RetrievalSettings(rrf_k=60))

    fact_both = uuid.uuid4()
    fact_kw_only = uuid.uuid4()
    fact_sem_only = uuid.uuid4()

    hits = [
        # fact_both is rank 1 in kw and rank 1 in sem
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact_both, channel="keyword", score=3.0, rank=1, query_id="q0"),
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact_both, channel="semantic", score=0.9, rank=1, query_id="q0"),
        # fact_kw_only is rank 2 in kw
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact_kw_only, channel="keyword", score=2.0, rank=2, query_id="q0"),
        # fact_sem_only is rank 2 in sem
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact_sem_only, channel="semantic", score=0.85, rank=2, query_id="q0"),
    ]

    candidates = fuser.fuse(hits)
    assert len(candidates) == 3

    # fact_both must be ranked first
    assert candidates[0].fact_id == fact_both
    expected_score_both = (1.0 / (60 + 1)) + (1.0 / (60 + 1))
    assert pytest.approx(candidates[0].fused_score) == expected_score_both

    # fact_kw_only and fact_sem_only both have rank 2: 1 / 62
    expected_single_score = 1.0 / (60 + 2)
    assert pytest.approx(candidates[1].fused_score) == expected_single_score
    assert pytest.approx(candidates[2].fused_score) == expected_single_score


def test_rrf_multi_query_max_aggregation() -> None:
    """Multi-query fusion aggregates by max per-query score and tracks query_count."""
    fuser = ReciprocalRankFuser(settings=RetrievalSettings(rrf_k=60, multi_query_aggregation="max"))

    fact1 = uuid.uuid4()
    fact2 = uuid.uuid4()

    # fact1 appears in q0 (rank 1) and q1 (rank 5)
    # fact2 appears in q1 (rank 2)
    hits = [
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact1, channel="keyword", score=3.0, rank=1, query_id="q0"),
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact1, channel="keyword", score=1.0, rank=5, query_id="q1"),
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=fact2, channel="keyword", score=2.0, rank=2, query_id="q1"),
    ]

    candidates = fuser.fuse(hits)
    assert len(candidates) == 2

    # fact1 has max score from q0: 1 / 61
    c1 = next(c for c in candidates if c.fact_id == fact1)
    assert pytest.approx(c1.fused_score) == 1.0 / 61
    assert c1.query_count == 2
    assert c1.best_channel_rank == 1

    # fact2 has score from q1: 1 / 62
    c2 = next(c for c in candidates if c.fact_id == fact2)
    assert pytest.approx(c2.fused_score) == 1.0 / 62
    assert c2.query_count == 1
    assert c2.best_channel_rank == 2


def test_rrf_deterministic_tie_breaking() -> None:
    """Equal fused scores tie-break by query_count desc, best_channel_rank asc, then fact_id asc."""
    fuser = ReciprocalRankFuser(settings=RetrievalSettings(rrf_k=60))

    # Two facts with identical scores and ranks, but distinct UUIDs
    f_a = uuid.UUID("11111111-1111-1111-1111-111111111111")
    f_b = uuid.UUID("22222222-2222-2222-2222-222222222222")

    hits = [
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=f_b, channel="keyword", score=1.0, rank=1, query_id="q0"),
        RetrievalHit(chunk_id=uuid.uuid4(), fact_id=f_a, channel="keyword", score=1.0, rank=1, query_id="q0"),
    ]

    candidates = fuser.fuse(hits)
    assert len(candidates) == 2

    # Tie break by UUID: f_a precedes f_b lexicographically
    assert candidates[0].fact_id == f_a
    assert candidates[1].fact_id == f_b

