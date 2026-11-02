"""Tests for the availability decision table and multi-source aggregation rules."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import ContextStrategy, DocumentType, GenerationProcessing, PostingAvailability
from job_automation.contracts.primitives import SourceKey
from job_automation.generation.input_availability import AvailabilityRechecker
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.identity.availability.models import SourcePostingAvailability
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestAvailabilityDecisionTable:
    def test_confirmed_unavailable_without_override_fails_preflight(
        self, engine: StorageEngine
    ) -> None:
        """Confirmed unavailable job without override returns job_unavailable error and records failure."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNAVAILABLE)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert manifest is None
        assert err is not None
        assert err.details.get("reason_code") == "job_unavailable"

        # Check durable preflight failure receipt
        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "failed"
        assert receipt.reason_code == "job_unavailable"

        # Check C13 request was marked Failed, never Running
        c13 = engine.generation_requests.get_request(req.request_id)
        assert c13 is not None
        assert c13.state == GenerationProcessing.FAILED

    def test_confirmed_unavailable_with_strict_override_proceeds_with_warning(
        self, engine: StorageEngine
    ) -> None:
        """Confirmed unavailable job with strict override seals and emits job_unavailable_overridden."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNAVAILABLE)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=True)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert "job_unavailable_overridden" in manifest.warnings
        assert manifest.allow_unavailable_job is True

        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "prepared"
        assert "job_unavailable_overridden" in receipt.warnings

    def test_unknown_availability_proceeds_with_warning(
        self, engine: StorageEngine
    ) -> None:
        """Unknown availability proceeds visibly with job_availability_unknown warning."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.UNKNOWN)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert "job_availability_unknown" in manifest.warnings

    def test_not_seen_availability_proceeds_with_warning(
        self, engine: StorageEngine
    ) -> None:
        """Not seen availability proceeds with job_not_seen warning and is not treated as unavailable."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.NOT_SEEN)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, allow_unavailable=False)
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None
        assert "job_not_seen" in manifest.warnings

    def test_multi_source_aggregation_active_source_preserves_vacancy(
        self, engine: StorageEngine
    ) -> None:
        """If one source is unavailable but another linked source is active, canonical job remains active."""
        job, _, _ = create_job_with_posting(engine, availability=PostingAvailability.ACTIVE)
        now_utc = datetime.now(timezone.utc)

        # Source 1 is unavailable
        sk1 = SourceKey(provider="arbeitnow", board_id="b1", source_posting_id="post-1")
        s1 = SourcePostingAvailability(
            source_key=sk1,
            scope_id="scope-1",
            canonical_job_id=job.canonical_job_id,
            availability=PostingAvailability.UNAVAILABLE,
            first_seen_at=now_utc,
            last_seen_at=now_utc,
            policy_fingerprint="pol-fp",
        )
        engine.availability.save_source_availability(s1)

        # Source 2 is active
        sk2 = SourceKey(provider="greenhouse", board_id="b2", source_posting_id="post-2")
        s2 = SourcePostingAvailability(
            source_key=sk2,
            scope_id="scope-2",
            canonical_job_id=job.canonical_job_id,
            availability=PostingAvailability.ACTIVE,
            first_seen_at=now_utc,
            last_seen_at=now_utc,
            policy_fingerprint="pol-fp",
        )
        engine.availability.save_source_availability(s2)

        rechecker = AvailabilityRechecker(engine=engine)
        check, err = rechecker.recheck_availability(job.canonical_job_id, allow_unavailable_job=False)
        assert err is None
        assert check is not None
        assert check.canonical_availability == PostingAvailability.ACTIVE
        assert check.warnings == []

