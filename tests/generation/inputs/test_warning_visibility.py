"""Tests verifying warning code visibility across preflight, manifest, bundle, and context receipts."""

from __future__ import annotations

from job_automation.contracts.enums import ContextStrategy, PostingAvailability
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestWarningVisibility:
    def test_unknown_availability_warning_propagated_to_all_layers(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNKNOWN)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.JSON)
        engine.generation_requests.create_request(req)

        # 1. Manifest has warning
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert "job_availability_unknown" in manifest.warnings

        # 2. Preflight receipt has warning
        preflight_receipt = service.inspect_preflight(req.request_id)
        assert preflight_receipt is not None
        assert "job_availability_unknown" in preflight_receipt.warnings

        # 3. Context bundle and context receipt have warning
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert "job_availability_unknown" in bundle.warnings

        ctx_receipt, r_err = service.get_context_receipt_by_request(req.request_id)
        assert r_err is None
        assert ctx_receipt is not None
        assert "job_availability_unknown" in ctx_receipt.warnings

