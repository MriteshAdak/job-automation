"""Tests for hierarchical parent context preservation and parent privacy (S05, RET-08, RET-09)."""

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


def test_parent_context_chain_preserved_in_root_to_leaf_order(tmp_path: Path) -> None:
    """RET-08: When a child achievement is retrieved, parent project and employment are included root-to-leaf."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    emp_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    achieve_id = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=emp_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Principal Engineer",
            organization="Global Systems Corp",
            start_date=PrecisionDate(value="2018-01-01", precision="day"),
            end_date=None,  # ongoing, null end date preserved
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=proj_id,
            parent_id=emp_id,
            kind=EvidenceFactKind.PROJECT,
            title="NextGen Order Book",
            provenance="cv.pdf",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=achieve_id,
            parent_id=proj_id,
            kind=EvidenceFactKind.SKILL,
            title="Sub-millisecond Latency Optimization",
            skills=["C++", "SIMD", "Kernel Bypass"],
            claims=["Optimized packet processing to 850 nanoseconds"],
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

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["SIMD kernel bypass packet processing"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
    )

    result, err = selector.select_context(req)
    assert err is None
    assert result is not None

    bundle = result.bundle
    ordered_ids = [f.fact_id for f in bundle.ordered_facts]

    # Verify that all 3 facts are in the bundle
    assert emp_id in ordered_ids
    assert proj_id in ordered_ids
    assert achieve_id in ordered_ids

    # Verify root-to-leaf ordering: emp precedes proj, which precedes achieve
    idx_emp = ordered_ids.index(emp_id)
    idx_proj = ordered_ids.index(proj_id)
    idx_achieve = ordered_ids.index(achieve_id)

    assert idx_emp < idx_proj < idx_achieve

    # Null end date remains null
    emp_fact = next(f for f in bundle.ordered_facts if f.fact_id == emp_id)
    assert emp_fact.end_date is None


def test_restricted_optional_parent_omitted_with_warning(tmp_path: Path) -> None:
    """RET-09: Restricted optional parent text is omitted, opaque parent_id and warning retained."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    private_parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    facts = [
        # Parent restricted from assessment (e.g. cv only)
        CandidateFact(
            fact_id=private_parent_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Confidential Defense Project",
            organization="Defense Corp",
            start_date=PrecisionDate(value="2017", precision="year"),
            provenance="cv.pdf",
            allowed_uses=["cv"],  # NOT allowed in assessment!
        ),
        # Child allowed in assessment
        CandidateFact(
            fact_id=child_id,
            parent_id=private_parent_id,
            kind=EvidenceFactKind.SKILL,
            title="Secure Enclave Architecture",
            skills=["Rust", "Cryptography"],
            claims=["Implemented secure hardware enclave attestation"],
            provenance="cv.pdf",
            allowed_uses=["assessment", "cv"],
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

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["Secure Enclave Architecture with Rust"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
        retrieval_settings=RetrievalSettings(strict_parents=False),
    )

    result, err = selector.select_context(req)
    assert err is None
    assert result is not None

    bundle = result.bundle
    # Child is present
    assert child_id in bundle.selected_fact_ids
    # Restricted parent text is NOT present
    assert private_parent_id not in bundle.selected_fact_ids

    # Warning regarding restricted parent is recorded
    assert any(str(private_parent_id) in w for w in bundle.warnings)


def test_restricted_parent_strict_mode_fails(tmp_path: Path) -> None:
    """RET-09: Under strict_parents=True, restricted parent raises ContextPermissionError."""
    db_path = tmp_path / "test.db"
    indexes_dir = tmp_path / "indexes"
    storage_engine = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    storage_engine.initialize_schema()

    private_parent_id = uuid.uuid4()
    child_id = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=private_parent_id,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Private Parent",
            provenance="cv.pdf",
            allowed_uses=["cv"],  # restricted from assessment
        ),
        CandidateFact(
            fact_id=child_id,
            parent_id=private_parent_id,
            kind=EvidenceFactKind.SKILL,
            title="Special Skill",
            skills=["Go"],
            provenance="cv.pdf",
            allowed_uses=["assessment", "cv"],
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

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["Special Skill in Go"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
        retrieval_settings=RetrievalSettings(strict_parents=True),
    )

    result, err = selector.select_context(req)
    assert result is None
    assert err is not None
    assert err.category == ErrorCategory.PERMISSION

