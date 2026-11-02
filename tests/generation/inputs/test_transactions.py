"""Tests for T0, T1, T3 transaction boundaries and rollback on simulated fault injection."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import StorageError
from job_automation.storage.repositories.generation_inputs import GenerationInputRepository
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestTransactions:
    def test_fault_injection_in_t1_rolls_back_completely(
        self, engine: StorageEngine
    ) -> None:
        """Simulate unexpected database crash while saving preflight receipt inside T1; verify seal is rolled back."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        # Mock save_preflight_receipt inside T1 to raise StorageError
        with patch.object(
            GenerationInputRepository,
            "save_preflight_receipt",
            side_effect=StorageError("Simulated disk error during receipt commit"),
        ):
            with pytest.raises(StorageError, match="Simulated disk error"):
                service.prepare_freeze(req, f"freeze:{req.request_id}")

        # Verify rollback: no seal exists in storage!
        seal = engine.generation_inputs.get_seal_by_request_id(req.request_id)
        assert seal is None

        # Verify no snapshots exist
        cursor = engine.conn.execute("SELECT COUNT(*) as cnt FROM generation_frozen_snapshots")
        assert cursor.fetchone()["cnt"] == 0

    def test_preflight_failure_atomically_persists_receipt_and_marks_failed(
        self, engine: StorageEngine
    ) -> None:
        """Confirmed unavailable job without override commits failed receipt and marks C13 Failed in one transaction."""
        from job_automation.contracts.enums import PostingAvailability, GenerationProcessing

        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNAVAILABLE)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None

        # Both receipt and C13 updated together
        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"

        c13 = engine.generation_requests.get_request(req.request_id)
        assert c13 is not None
        assert c13.state == GenerationProcessing.FAILED

