"""Unit tests for embedding call audit recording and privacy boundaries."""

from __future__ import annotations

from job_automation.context.index_embeddings import IndexEmbeddingCoordinator
from job_automation.context.index_model_audit import IndexAuditSink
from tests.context.index_test_helpers import (
    create_test_chunk_set,
    create_test_embedding_config,
    create_test_index_settings,
)
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider


def test_audit_sink_records_metadata_without_private_text() -> None:
    cs = create_test_chunk_set()
    cfg = create_test_embedding_config(dimension=8)
    settings = create_test_index_settings(dimension=8)
    provider = DeterministicFakeEmbeddingProvider(dimension=8)
    audit = IndexAuditSink()

    coordinator = IndexEmbeddingCoordinator(
        provider=provider, config=cfg, settings=settings, audit_sink=audit
    )
    coordinator.embed_chunks(cs.chunks)

    assert len(audit.call_records) == 1
    rec = audit.call_records[0]

    assert "call_id" in rec
    assert rec["model_identifier"] == "fake-embedder"
    assert rec["dimension"] == 8
    assert rec["item_count"] == len(cs.chunks)

    # Ensure no chunk claim text, title, or raw text leaks into the audit record
    for chunk in cs.chunks:
        assert chunk.title not in str(rec)
        assert chunk.retrieval_text not in str(rec)

