"""Tests for ContextSelector execution on native Windows paths with spaces and German umlauts."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

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


def test_selector_on_windows_path_with_spaces_and_umlauts(tmp_path: Path) -> None:
    """Verify context selector runs cleanly on Windows paths containing spaces and German characters."""
    special_dir = tmp_path / "Bewerbung Prüfung und Tests (München)"
    special_dir.mkdir(parents=True, exist_ok=True)

    db_path = special_dir / "automation_prüf.db"
    indexes_dir = special_dir / "retrieval indizes"

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

    req = ContextSelectionRequest(
        strategy=ContextStrategy.RAG,
        snapshot=snapshot,
        purpose="assessment",
        canonical_job_id=uuid.uuid4(),
        posting_revision=posting.raw_content_hash,
        job_content=posting,
        requirements=["C++ distributed systems in München"],
        model_identifier="test-model",
        context_limit=4096,
        embedding_config=emb_config,
    )

    result, err = selector.select_context(req)
    assert err is None
    assert result is not None
    assert result.bundle.strategy == ContextStrategy.RAG
    assert len(result.bundle.ordered_facts) > 0

