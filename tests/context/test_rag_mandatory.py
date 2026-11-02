"""Tests for mandatory context reservation, bypass, and overflow (S05, RET-02, RET-10)."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.selector_records import ContextSelectionRequest
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.errors import ErrorCategory
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_mandatory_context_bypasses_top_k_zero(tmp_path: Path) -> None:
    """RET-02: With top_k=0, all mandatory chronology and eligibility facts are still present in C09."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    emp_id = uuid.uuid4()
    edu_id = uuid.uuid4()
    skill_id = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=emp_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Software Engineer",
            organization="Tech Corp",
            start_date=PrecisionDate(value="2020", precision="year"),
            claims=["Built distributed backend systems"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=edu_id,
            kind=EvidenceFactKind.EDUCATION,
            title="B.Sc. Informatics",
            organization="University",
            start_date=PrecisionDate(value="2016", precision="year"),
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=skill_id,
            kind=EvidenceFactKind.SKILL,
            title="Python and C++",
            claims=["Advanced proficiency"],
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
    ]

    snapshot = create_selector_test_snapshot(facts=facts)
    posting = create_selector_test_posting()
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    _, store, emb_config = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=provider,
    )

    selector = ContextSelectorV2Service(
        index_store=store,
        model_provider=provider,
    )

    # Explicitly set top_k = 0
    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["Python and C++ proficiency"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
        retrieval_settings=RetrievalSettings(top_k=0),
    )

    result, err = selector.select_context(req)
    assert err is None
    assert result is not None

    bundle = result.bundle
    # Both mandatory facts (employment and education) are included!
    assert emp_id in bundle.selected_fact_ids
    assert edu_id in bundle.selected_fact_ids
    # Non-mandatory optional skill fact was NOT admitted because top_k=0
    assert skill_id not in bundle.selected_fact_ids

    # Structured mandatory context is intact
    assert bundle.structured_mandatory is not None
    assert emp_id in bundle.structured_mandatory.mandatory_fact_ids
    assert edu_id in bundle.structured_mandatory.mandatory_fact_ids


def test_mandatory_only_overflow_fails_visibly(tmp_path: Path) -> None:
    """RET-10: When mandatory context alone exceeds the window, raises context_budget error."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    snapshot = create_selector_test_snapshot()
    posting = create_selector_test_posting()
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    _, store, emb_config = build_and_activate_test_index(
        storage_engine=storage_engine,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=provider,
    )

    selector = ContextSelectorV2Service(
        index_store=store,
        model_provider=provider,
    )

    # Extremely small window (e.g. 50 tokens) with large reserves
    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["C++ engineer"],
        model_identifier="test-model",
        context_limit=50,
        output_reserve=30,
        safety_allowance=10,
        embedding_config=emb_config,
    )

    result, err = selector.select_context(req)
    assert result is None
    assert err is not None
    assert err.category == ErrorCategory.CONTEXT_BUDGET
    assert "Mandatory context alone exceeds" in err.message or "exhausted by output reserve" in err.message

