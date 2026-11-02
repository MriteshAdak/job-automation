"""Tests for inspectable preflight failure durability, reason codes, and missing inputs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import PostingAvailability
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestPreflightFailures:
    def test_missing_canonical_job_fails_with_inspectable_receipt(
        self, engine: StorageEngine
    ) -> None:
        """Missing canonical job produces durable PreflightReceipt even when C13 cannot be inserted."""
        publish_approved_profile(engine)
        missing_job_id = uuid.uuid4()

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=missing_job_id)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None
        assert err.details.get("reason_code") == "job_not_found"

        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"
        assert receipt.reason_code == "job_not_found"

    def test_unapproved_profile_fails_with_inspectable_receipt(
        self, engine: StorageEngine
    ) -> None:
        """Missing approved profile produces profile_unapproved failure."""
        job, _, _ = create_job_with_posting(engine)
        # Note: no profile published in database!

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None
        assert err.details.get("reason_code") == "profile_unapproved"

        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"
        assert receipt.reason_code == "profile_unapproved"

    def test_job_content_hash_mismatch_fails_with_inspectable_receipt(
        self, engine: StorageEngine
    ) -> None:
        """Tampered job content hash in revision produces job_snapshot_mismatch."""
        job, rev, posting = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        # Corrupt the revision content_hash in storage
        corrupted_rev = rev.model_copy(update={"content_hash": "sha256:" + "0" * 64})
        engine.canonical_jobs.save_revision(corrupted_rev)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None
        assert err.details.get("reason_code") == "job_snapshot_mismatch"

        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"
        assert receipt.reason_code == "job_snapshot_mismatch"

