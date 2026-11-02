"""Tests for request-owned index pin enforcement and cross-request pin isolation."""

from __future__ import annotations

import uuid

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


class TestPinAuthorization:
    def test_released_pin_prevents_context_building(
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

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        seal, _ = service.get_seal(req.request_id)
        assert seal is not None
        assert seal.index_pin_id is not None

        # Prematurely release the pin in storage
        engine.context_indexes.release_pin(seal.index_pin_id)

        # Attempt to build context must fail because pin is no longer active
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert bundle is None
        assert ctx_err is not None
        assert ctx_err.details.get("reason_code") == "frozen_index_mismatch"
