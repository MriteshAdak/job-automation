"""Tests for RAG whole-prompt packing, group omission, and budget bounds (S05, RET-10)."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.retrieval_settings import RetrievalSettings
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.selector_records import ContextSelectionRequest
from job_automation.contracts.enums import ContextStrategy, EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_oversized_candidate_omitted_and_smaller_later_candidate_admitted(tmp_path: Path) -> None:
    """RET-10: An oversized higher-ranked group is skipped with budget_omitted; later smaller group is admitted."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    emp_id = uuid.uuid4()
    large_fact_id = uuid.uuid4()
    small_fact_id = uuid.uuid4()

    facts = [
        # Small employment anchor (mandatory)
        CandidateFact(
            fact_id=emp_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Software Developer",
            organization="Small Co",
            start_date=PrecisionDate(value="2020", precision="year"),
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        # Very large optional fact (lots of claims and text)
        CandidateFact(
            fact_id=large_fact_id,
            kind=EvidenceFactKind.SKILL,
            title="Large Architecture Achievement",
            skills=["Kubernetes", "Cloud", "Distributed"],
            claims=["Claim " + "x" * 200 for _ in range(10)],  # ~2000 chars of text
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        # Small optional fact
        CandidateFact(
            fact_id=small_fact_id,
            kind=EvidenceFactKind.SKILL,
            title="Python Tools",
            skills=["Python", "CLI"],
            claims=["Created small automation script"],
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

    # Window calibrated so mandatory + small fact fits, but mandatory + large fact overflows!
    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["Kubernetes cloud", "Python automation script"],
        model_identifier="test-model",
        context_limit=1100,
        output_reserve=100,
        safety_allowance=20,
        embedding_config=emb_config,
    )

    result, err = selector.select_context(req)
    assert err is None
    assert result is not None

    bundle = result.bundle
    trace = result.trace
    assert trace is not None

    # Mandatory fact is admitted
    assert emp_id in bundle.selected_fact_ids

    # Large fact was omitted due to budget
    assert large_fact_id in trace.budget_omitted_fact_ids
    assert large_fact_id not in bundle.selected_fact_ids

    # Small fact was admitted!
    assert small_fact_id in bundle.selected_fact_ids

    # Warning regarding budget omission is present
    assert any("OPTIONAL_BUDGET_OMISSION" in w for w in bundle.warnings)
    assert bundle.budget_report is not None
    assert bundle.budget_report.fits is True

