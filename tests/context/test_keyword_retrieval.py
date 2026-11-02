"""Tests for keyword channel retrieval (S04, RET-04, RET-06)."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.keyword_retrieval import KeywordRetriever
from job_automation.context.queries import DefaultQueryBuilder
from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_keyword_retrieval_exact_tokens(tmp_path: Path) -> None:
    """RET-04: Exact skill tokens (C++, C#, .NET) and German umlauts are retrieved."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    cpp_fact_id = uuid.uuid4()
    csharp_fact_id = uuid.uuid4()
    python_fact_id = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=cpp_fact_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior C++ Core Developer",
            organization="Trading Systems GmbH",
            start_date=PrecisionDate(value="2020", precision="year"),
            skills=["C++", "Linux", "Low-Latency"],
            claims=["Developed order book matching in München"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=csharp_fact_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title=".NET Backend Architect",
            organization="Enterprise AG",
            start_date=PrecisionDate(value="2018", precision="year"),
            skills=["C#", ".NET", "Azure"],
            claims=["Architected distributed .NET services"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=python_fact_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Data Scientist",
            organization="AI Labs",
            start_date=PrecisionDate(value="2021", precision="year"),
            skills=["Python", "PyTorch"],
            claims=["Trained NLP transformer models"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
    ]

    snapshot = create_selector_test_snapshot(facts=facts)
    _, store, _ = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
    )

    from job_automation.contracts.retrieval_index import IndexReadRequest
    handle, _ = store.open(IndexReadRequest(candidate_id=snapshot.candidate_id, purpose="assessment"))
    assert handle is not None

    try:
        builder = DefaultQueryBuilder()
        retriever = KeywordRetriever(settings=RetrievalSettings(per_channel_limit=10))

        # 1. Query for C++ in München
        qset1 = builder.build_queries(["Senior C++ developer in München"])
        hits1 = retriever.retrieve(qset1, handle)

        assert len(hits1) >= 1
        # C++ fact is top rank
        assert hits1[0].fact_id == cpp_fact_id
        assert hits1[0].rank == 1
        assert hits1[0].channel == "keyword"
        assert hits1[0].score >= 2.0  # matched 'c++' and 'münchen'

        # 2. Query for C# and .NET
        qset2 = builder.build_queries(["C# and .NET enterprise architect"])
        hits2 = retriever.retrieve(qset2, handle)

        assert len(hits2) >= 1
        assert hits2[0].fact_id == csharp_fact_id
        assert hits2[0].rank == 1
        assert hits2[0].score >= 2.0  # matched 'c#' and '.net'

    finally:
        handle.close()


def test_keyword_retrieval_empty_when_no_match(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    snapshot = create_selector_test_snapshot()
    _, store, _ = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
    )

    from job_automation.contracts.retrieval_index import IndexReadRequest
    handle, _ = store.open(IndexReadRequest(candidate_id=snapshot.candidate_id, purpose="assessment"))
    assert handle is not None

    try:
        builder = DefaultQueryBuilder()
        retriever = KeywordRetriever()

        # Unrelated query with zero term overlap
        qset = builder.build_queries(["Dentistry orthodontics dental surgeon"])
        hits = retriever.retrieve(qset, handle)
        assert len(hits) == 0

    finally:
        handle.close()

