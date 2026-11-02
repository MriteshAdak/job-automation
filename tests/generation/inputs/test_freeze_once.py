"""Tests for freeze-once invariance, idempotent replay, and conflict detection."""

from __future__ import annotations

import uuid

from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestFreezeOnce:
    def test_freeze_once_idempotent_replay_with_different_op_ids(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        # First call
        manifest1, err1 = service.prepare_freeze(req, "freeze:op:1")
        assert err1 is None
        assert manifest1 is not None

        # Second call with different op id
        manifest2, err2 = service.prepare_freeze(req, "freeze:op:2")
        assert err2 is None
        assert manifest2 is not None

        # Exactly identical manifest hash and content
        assert manifest1.manifest_hash == manifest2.manifest_hash
        assert manifest1.frozen_at == manifest2.frozen_at

    def test_freeze_conflict_on_changed_options(self, engine: StorageEngine) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest1, err1 = service.prepare_freeze(req, "freeze:op:1")
        assert err1 is None

        # Re-freeze with modified options (allow_unavailable=True) raises freeze_conflict
        conflict_req = req.model_copy(update={"allow_unavailable_job": True})
        manifest2, err2 = service.prepare_freeze(conflict_req, "freeze:op:2")
        assert manifest2 is None
        assert err2 is not None
        assert err2.details.get("reason_code") == "freeze_conflict"

    def test_returned_manifest_is_detached(self, engine: StorageEngine) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        manifest, _ = service.prepare_freeze(req, "freeze:op:1")
        assert manifest is not None

        # Mutate the returned manifest object
        manifest.warnings.append("mutated_warning")
        object.__setattr__(manifest, "target_language", "fr")

        # Reopen from storage
        reopened, _ = service.reopen_freeze(manifest.manifest_id)
        assert reopened is not None
        assert "mutated_warning" not in reopened.warnings
        assert reopened.target_language == "de"

