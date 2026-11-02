"""Tests for recipe freezing, requirements extraction, and prompt instructions."""

from __future__ import annotations

from job_automation.contracts.enums import DocumentType
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestRecipeFreeze:
    def test_recipe_captures_requirements_and_instructions(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(
            engine,
            description="Detailed Job Description:\n- Advanced Python async programming\n- FastAPI microservices\n- Event-driven architecture with Kafka",
        )
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, doc_type=DocumentType.CV)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        seal, _ = service.get_seal(req.request_id)
        assert seal is not None
        assert seal.recipe.context_limit == 8192
        assert seal.recipe.output_reserve == 512
        assert len(seal.recipe.requirements) >= 2
        assert any("Python" in r for r in seal.recipe.requirements)
        assert seal.recipe.recipe_digest.startswith("sha256:")

