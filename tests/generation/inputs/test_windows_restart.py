"""Tests for process restart and persistent database reopen under native Windows conditions."""

from __future__ import annotations

from pathlib import Path

from job_automation.contracts.enums import ContextStrategy
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestWindowsRestart:
    def test_seals_and_receipts_survive_connection_close_and_reopen(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "restart_test.db"
        eng1 = StorageEngine(db_path=db_path)
        eng1.initialize_schema()

        job, _, _ = create_job_with_posting(eng1)
        profile = publish_approved_profile(eng1)

        service1 = DefaultGenerationInputService(engine=eng1)
        req = make_request(job_id=job.canonical_job_id)
        eng1.generation_requests.create_request(req)

        manifest, err = service1.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        bundle, ctx_err = service1.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None

        # Simulate process termination / closing connection
        eng1.close()

        # Reopen on a second engine instance simulating restarted process
        eng2 = StorageEngine(db_path=db_path)
        service2 = DefaultGenerationInputService(engine=eng2)

        # 1. Preflight receipt survives
        receipt = service2.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "prepared"

        # 2. Reopen freeze survives
        reopened_manifest, r_err = service2.reopen_freeze(manifest.manifest_id)
        assert r_err is None
        assert reopened_manifest is not None
        assert reopened_manifest.manifest_hash == manifest.manifest_hash

        # 3. Context receipt survives and replays
        replayed_bundle, c_err = service2.build_context(reopened_manifest, "ctx:replay")
        assert c_err is None
        assert replayed_bundle is not None
        assert replayed_bundle.content_fingerprint == bundle.content_fingerprint

        eng2.close()

