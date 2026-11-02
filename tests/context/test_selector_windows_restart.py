"""Tests for ContextSelector state survival and deterministic output across storage restarts."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from job_automation.context.index_reader import IndexStore
from job_automation.context.selector import ContextSelectorV2Service
from job_automation.context.selector_records import ContextSelectionRequest
from job_automation.contracts.enums import ContextStrategy
from job_automation.storage.engine import StorageEngine
from tests.context.selector_test_helpers import (
    build_and_activate_test_index,
    create_selector_test_posting,
    create_selector_test_snapshot,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_selector_deterministic_across_storage_restart(tmp_path: Path) -> None:
    """Index and selector reproduce identical bundles across database close/reopen."""
    db_path = tmp_path / "restart.db"
    indexes_dir = tmp_path / "indexes"

    engine1 = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    engine1.initialize_schema()

    snapshot = create_selector_test_snapshot()
    posting = create_selector_test_posting()
    provider = DeterministicFakeEmbeddingProvider(dimension=8)

    _, _, emb_config = build_and_activate_test_index(
        storage_engine=engine1,
        indexes_dir=indexes_dir,
        snapshot=snapshot,
        purpose="assessment",
        dimension=8,
        provider=provider,
    )

    selector1 = ContextSelectorV2Service(
        index_store=IndexStore(indexes_dir=indexes_dir, repository=engine1.context_indexes),
        model_provider=provider,
    )

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["C++ distributed systems"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
    )

    res1, err1 = selector1.select_context(req)
    assert err1 is None
    assert res1 is not None

    # Close first storage engine
    engine1.close()

    # Reopen fresh storage engine pointing to the same disk files
    engine2 = StorageEngine(db_path=db_path, indexes_dir=indexes_dir)
    store2 = IndexStore(indexes_dir=indexes_dir, repository=engine2.context_indexes)
    selector2 = ContextSelectorV2Service(
        index_store=store2,
        model_provider=provider,
    )

    res2, err2 = selector2.select_context(req)
    assert err2 is None
    assert res2 is not None

    # Byte-for-byte and logical fingerprint reproducibility
    assert res1.construction_fingerprint == res2.construction_fingerprint
    assert res1.bundle.content_fingerprint == res2.bundle.content_fingerprint
    assert res1.bundle.selected_fact_ids == res2.bundle.selected_fact_ids
    assert res1.bundle.ordered_facts == res2.bundle.ordered_facts

    engine2.close()

