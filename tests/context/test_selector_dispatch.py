"""Tests for shared context selector dispatch (S02, RET-01)."""

from __future__ import annotations

import uuid
import pytest
from pathlib import Path

from job_automation.context.errors import ContextValidationError
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.selector_records import (
    ContextSelectionRequest,
    ContextSelectionResult,
)
from job_automation.contracts.enums import ContextStrategy
from job_automation.contracts.errors import ErrorCategory
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_shared_selector_json_delegation_without_index(tmp_path: Path) -> None:
    """RET-01: JSON delegation works with no index configured and makes zero model/index calls."""
    snapshot = create_selector_test_snapshot()
    posting = create_selector_test_posting()

    selector = ContextSelectorV2Service(
        index_store=None,  # No index store configured
        model_provider=None,  # No model provider
    )

    req = ContextSelectionRequest(
        strategy=ContextStrategy.JSON,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["5+ years C++ experience", "Python backend"],
        model_identifier="test-model",
        context_limit=4096,
    )

    result, err = selector.select_context(req)

    assert err is None
    assert result is not None
    assert isinstance(result, ContextSelectionResult)

    bundle = result.bundle
    assert bundle.strategy == ContextStrategy.JSON
    assert bundle.query_version is None
    assert bundle.index_version is None
    assert bundle.retrieval_settings is None
    assert bundle.retrieval_audit is None

    # Complete permitted facts included
    assert len(bundle.ordered_facts) == len(snapshot.evidence_records)
    assert result.trace is None
    assert result.rendered_prompt is not None


def test_shared_selector_both_strategies_parity(tmp_path: Path) -> None:
    """RET-01: Both JSON and RAG receive identical preparation and mandatory facts for the same snapshot."""
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

    # 1. Run JSON
    req_json = ContextSelectionRequest(
        strategy=ContextStrategy.JSON,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["C++ matching engine", "Distributed systems"],
        model_identifier="test-model",
        context_limit=4096,
    )
    res_json, err_json = selector.select_context(req_json)
    assert err_json is None
    assert res_json is not None

    # 2. Run RAG
    req_rag = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["C++ matching engine", "Distributed systems"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
    )
    res_rag, err_rag = selector.select_context(req_rag)
    assert err_rag is None
    assert res_rag is not None

    # Compare shared preparation parity
    bundle_json = res_json.bundle
    bundle_rag = res_rag.bundle

    assert bundle_json.mandatory_fact_ids == bundle_rag.mandatory_fact_ids
    assert bundle_json.mandatory_context == bundle_rag.mandatory_context
    assert bundle_json.structured_mandatory == bundle_rag.structured_mandatory
    assert bundle_json.candidate_id == bundle_rag.candidate_id
    assert bundle_json.purpose == bundle_rag.purpose

    # RAG has retrieval metadata
    assert bundle_rag.query_version is not None
    assert bundle_rag.index_version is not None
    assert bundle_rag.retrieval_settings is not None
    assert bundle_rag.retrieval_audit is not None
    assert res_rag.trace is not None


def test_selector_missing_index_for_rag_fails_visibly() -> None:
    """Calling RAG without configured IndexStore fails with MISSING_CONFIGURATION."""
    snapshot = create_selector_test_snapshot()
    posting = create_selector_test_posting()

    selector = ContextSelectorV2Service(index_store=None)

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        model_identifier="test-model",
        context_limit=4096,
    )

    result, err = selector.select_context(req)
    assert result is None
    assert err is not None
    assert err.category == ErrorCategory.MISSING_CONFIGURATION


def test_selector_unapproved_snapshot_rejected() -> None:
    """An unapproved snapshot fails validation immediately for both strategies."""
    from job_automation.contracts.profile import ProfileApprovalMetadata
    from datetime import datetime, timezone

    snapshot = create_selector_test_snapshot()
    unapproved_snapshot = snapshot.model_copy(
        update={
            "approval_metadata": ProfileApprovalMetadata(
                is_approved=False,
                approved_by="none",
                approved_at=datetime.now(timezone.utc),
            )
        }
    )
    posting = create_selector_test_posting()
    selector = ContextSelectorV2Service()

    req = ContextSelectionRequest(
        strategy=ContextStrategy.JSON,
        snapshot=unapproved_snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        model_identifier="test-model",
        context_limit=4096,
    )

    result, err = selector.select_context(req)
    assert result is None
    assert err is not None
    assert err.category == ErrorCategory.VALIDATION
    assert "explicit human approval" in err.message
