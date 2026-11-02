"""Tests for RAG context strategy assembly, auxiliary retrieval traces, and evidence references."""

from __future__ import annotations

from job_automation.contracts.enums import ContextStrategy
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.fakes.index_embeddings import DeterministicFakeEmbeddingProvider
from tests.generation.inputs.conftest import (
    build_and_activate_test_rag_index,
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestRagContext:
    def test_rag_context_produces_bundle_and_persists_trace(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)
        gen_id = build_and_activate_test_rag_index(engine, profile, purpose="cv", dimension=8)

        fake_model = DeterministicFakeEmbeddingProvider(dimension=8)
        service = DefaultGenerationInputService(engine=engine, model_provider=fake_model)

        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.RAG)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert bundle.strategy == ContextStrategy.RAG

        # Inspect durable context receipt for complete ContextSelectionResult
        receipt, r_err = service.get_context_receipt_by_request(req.request_id)
        assert r_err is None
        assert receipt is not None
        assert receipt.result.bundle.strategy == ContextStrategy.RAG
        assert receipt.result.rendered_prompt is not None
        assert len(receipt.result.rendered_prompt.full_prompt) > 0
        assert receipt.result.trace is not None
        assert len(receipt.result.trace.selected_fact_ids) > 0
