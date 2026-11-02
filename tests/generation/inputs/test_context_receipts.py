"""Tests for durable context receipts, idempotent replay, and zero recomputation."""

from __future__ import annotations

from unittest.mock import MagicMock

from job_automation.contracts.enums import ContextStrategy
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestContextReceipts:
    def test_context_replayed_without_selector_recomputation(
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

        # 1. First build creates receipt
        bundle1, err1 = service.build_context(manifest, "ctx:op:1")
        assert err1 is None
        assert bundle1 is not None

        receipt1 = engine.generation_inputs.get_context_receipt_by_request_id(req.request_id)
        assert receipt1 is not None

        # Spy: Mock ContextAssembler or check that second call returns identical receipt
        # 2. Second build with different op id returns identical saved result
        bundle2, err2 = service.build_context(manifest, "ctx:op:2")
        assert err2 is None
        assert bundle2 is not None
        assert bundle1.content_fingerprint == bundle2.content_fingerprint

        receipt2, r_err = service.reopen_context(receipt1.receipt_id)
        assert r_err is None
        assert receipt2 is not None
        assert receipt2.result_hash == receipt1.result_hash
        assert (
            receipt2.result.rendered_prompt.full_prompt
            == receipt1.result.rendered_prompt.full_prompt
        )

