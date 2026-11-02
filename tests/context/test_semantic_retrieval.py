"""Tests for semantic channel retrieval (S04, RET-05)."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.queries import DefaultQueryBuilder
from job_automation.context.query_embeddings import QueryEmbeddingCoordinator
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.semantic_retrieval import SemanticRetriever
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.contracts.retrieval_index import IndexReadRequest
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_semantic_retrieval_scores_and_ranks(tmp_path: Path) -> None:
    """RET-05: Semantic retrieval ranks candidates based on vector cosine similarity."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    sched_fact_id = uuid.uuid4()
    facts = [
        CandidateFact(
            fact_id=sched_fact_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Executive Assistant",
            organization="City Office",
            start_date=PrecisionDate(value="2021", precision="year"),
            skills=["Office Management", "Communication"],
            claims=["Managed calendar schedules, room bookings, and executive itineraries"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
    ]

    snapshot = create_selector_test_snapshot(facts=facts)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    _, store, emb_config = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=provider,
    )

    handle, _ = store.open(IndexReadRequest(candidate_id=snapshot.candidate_id, purpose="assessment"))
    assert handle is not None

    try:
        builder = DefaultQueryBuilder()
        qset = builder.build_queries(["coordinate appointments and manage agendas"])

        coord = QueryEmbeddingCoordinator(provider)
        q_vecs, _ = coord.embed_queries(qset, emb_config, normalize=True)

        retriever = SemanticRetriever(settings=RetrievalSettings(per_channel_limit=10))
        hits = retriever.retrieve(qset, q_vecs, handle)

        assert len(hits) == 1
        assert hits[0].fact_id == sched_fact_id
        assert hits[0].channel == "semantic"
        assert hits[0].rank == 1
        assert -1.0 <= hits[0].score <= 1.0

    finally:
        handle.close()


def test_semantic_retrieval_threshold_filtering(tmp_path: Path) -> None:
    """Threshold filter discards candidates below semantic_threshold."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    snapshot = create_selector_test_snapshot()
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    _, store, emb_config = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=provider,
    )

    handle, _ = store.open(IndexReadRequest(candidate_id=snapshot.candidate_id, purpose="assessment"))
    assert handle is not None

    try:
        builder = DefaultQueryBuilder()
        qset = builder.build_queries(["Python backend"])
        coord = QueryEmbeddingCoordinator(provider)
        q_vecs, _ = coord.embed_queries(qset, emb_config, normalize=True)

        # Impossibly high threshold
        strict_retriever = SemanticRetriever(
            settings=RetrievalSettings(semantic_threshold=0.999999)
        )
        hits = strict_retriever.retrieve(qset, q_vecs, handle)
        assert len(hits) == 0

    finally:
        handle.close()

