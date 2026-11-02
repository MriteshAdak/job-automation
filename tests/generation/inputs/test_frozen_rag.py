"""Tests for RAG index resolution, validation, pinning, and frozen retrieval."""

from __future__ import annotations

import uuid

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider
from tests.generation.inputs.conftest import (
    build_and_activate_test_rag_index,
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestFrozenRag:
    def test_missing_rag_index_fails_preflight(self, engine: StorageEngine) -> None:
        """RAG strategy requested but no compatible index built -> fails preflight."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)
        # Note: no RAG index built!

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.RAG)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None
        assert err.details.get("reason_code") == "frozen_index_mismatch"

        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"

    def test_compatible_rag_index_is_pinned_and_retrieves_evidence(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)
        gen_id = build_and_activate_test_rag_index(engine, profile, purpose="cv", dimension=8)

        from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider
        fake_model = DeterministicFakeEmbeddingProvider(dimension=8)
        service = DefaultGenerationInputService(engine=engine, model_provider=fake_model)

        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.RAG)
        engine.generation_requests.create_request(req)

        # 1. Prepare freeze pins index
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert "pinned_index_generation_id" in manifest.snapshot_refs
        assert manifest.snapshot_refs["pinned_index_generation_id"] == str(gen_id)

        # Verify pin in database
        assert engine.context_indexes.is_generation_pinned(gen_id) is True

        # 2. Build context using pinned index
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert bundle.strategy == ContextStrategy.RAG
        assert len(bundle.ordered_facts) > 0
