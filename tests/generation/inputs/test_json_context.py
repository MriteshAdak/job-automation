"""Tests for JSON context strategy assembly and budget boundary enforcement."""

from __future__ import annotations

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.generation.input_records import GenerationInputSettings
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestJsonContext:
    def test_json_context_assembles_purpose_eligible_facts(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.JSON)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert bundle.strategy == ContextStrategy.JSON
        assert len(bundle.ordered_facts) == 2
        assert bundle.posting_revision == job.revisions[0].content_hash

    def test_json_context_budget_overflow_returns_classified_error_without_switch(
        self, engine: StorageEngine
    ) -> None:
        """When token limit is smaller than mandatory prompt reserve, returns context_budget without strategy switch."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        # Settings with tiny context limit (50 tokens)
        settings = GenerationInputSettings(default_context_limit=50, default_output_reserve=20, default_safety_allowance=10)
        service = DefaultGenerationInputService(engine=engine, settings=settings)

        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.JSON)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert bundle is None
        assert ctx_err is not None
        # Budget failure category
        assert ctx_err.category.value == "context_budget"

