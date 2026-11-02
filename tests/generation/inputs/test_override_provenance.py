"""Tests for explicit candidate override provenance tracking and warning propagation."""

from __future__ import annotations

import uuid

from job_automation.contracts.enums import PostingAvailability
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestOverrideProvenance:
    def test_override_provenance_bound_to_request_identity(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNAVAILABLE)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=True)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        seal, seal_err = service.get_seal(req.request_id)
        assert seal_err is None
        assert seal is not None

        # Verify provenance was saved
        assert seal.options.allow_unavailable_job is True
        assert seal.options.override_provenance == f"candidate_request:{req.request_id}"
        assert seal.options.override_timestamp is not None
        assert seal.availability_check.override_applied is True
        assert seal.availability_check.override_provenance == f"candidate_request:{req.request_id}"
        assert "job_unavailable_overridden" in seal.manifest.warnings

