"""Tests for the GEN-02 crash and interruption matrix."""

from __future__ import annotations

from unittest.mock import patch

from job_automation.contracts.enums import ContextStrategy, GenerationProcessing, PostingAvailability
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestCrashMatrix:
    def test_crash_after_seal_before_worker_claim_resumes_cleanly(
        self, engine: StorageEngine
    ) -> None:
        """When seal is committed (T1) but worker crashes before claim (T2), request stays Pending and reopens identical seal."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        # 1. Prepare freeze commits T1
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        # Verify C13 request is still PENDING in storage (T2 has not run yet)
        c13 = engine.generation_requests.get_request(req.request_id)
        assert c13 is not None
        assert c13.state == GenerationProcessing.PENDING

        # 2. Worker restarts or retries: prepare_freeze reopens exact same seal without re-reading mutable profile
        manifest2, err2 = service.prepare_freeze(req, f"freeze:{req.request_id}:restart")
        assert err2 is None
        assert manifest2 is not None
        assert manifest2.manifest_hash == manifest.manifest_hash

    def test_crash_after_preflight_failure_remains_inspectable_without_running(
        self, engine: StorageEngine
    ) -> None:
        """Preflight rejection commits failure durable receipt; recovery never transitions to Running."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNAVAILABLE)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None

        # Reopen on fresh service instance simulating crash recovery
        fresh_service = DefaultGenerationInputService(engine=engine)
        receipt = fresh_service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"
        assert receipt.reason_code == "job_unavailable"

        c13 = engine.generation_requests.get_request(req.request_id)
        assert c13.state == GenerationProcessing.FAILED

    def test_failure_during_context_assembly_preserves_seal_intact(
        self, engine: StorageEngine
    ) -> None:
        """If context assembly fails (e.g. transient model error), seal remains valid and intact for retry."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        manifest, _ = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is not None

        # Simulate selector failure during first build
        with patch.object(
            service.context_assembler,
            "assemble_context",
            side_effect=Exception("Transient tokenizer memory failure"),
        ):
            try:
                service.build_context(manifest, "ctx:op:1")
            except Exception:
                pass

        # Seal in storage is still completely intact
        seal, s_err = service.get_seal(req.request_id)
        assert s_err is None
        assert seal is not None
        assert seal.manifest.manifest_hash == manifest.manifest_hash

        # Retry context build without simulated failure succeeds cleanly
        bundle, retry_err = service.build_context(manifest, "ctx:op:2")
        assert retry_err is None
        assert bundle is not None

