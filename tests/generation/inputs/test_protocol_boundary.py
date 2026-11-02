"""Tests verifying protocol conformance and standalone boundary execution."""

from __future__ import annotations

import uuid

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.input_ports import StandaloneGenerationInputService
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.ports import GenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestProtocolBoundary:
    def test_default_service_implements_protocols(self, engine: StorageEngine) -> None:
        service = DefaultGenerationInputService(engine=engine)
        assert isinstance(service, GenerationInputService)
        assert isinstance(service, StandaloneGenerationInputService)

    def test_standalone_execution_without_worker_or_salesforce(
        self, engine: StorageEngine
    ) -> None:
        """Demonstrate that prepare_freeze, inspect_preflight, and build_context run in standalone Python."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)
        freeze_op = f"freeze:{req.request_id}"

        # 1. Prepare freeze
        manifest, err = service.prepare_freeze(req, freeze_op)
        assert err is None
        assert manifest is not None
        assert manifest.canonical_job_id == job.canonical_job_id

        # Exactly one non-null guarantee
        assert (manifest is not None) ^ (err is not None)

        # 2. Inspect preflight
        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "prepared"
        assert receipt.seal_id == f"seal:{req.request_id}"

        # 3. Build context
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert bundle.posting_revision == job.revisions[0].content_hash
        assert (bundle is not None) ^ (ctx_err is not None)

