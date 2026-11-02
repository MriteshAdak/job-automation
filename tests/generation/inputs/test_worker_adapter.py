"""Tests verifying seamless integration of real DefaultGenerationInputService into GEN-01 coordinator."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.contracts.enums import GenerationProcessing
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import GenerationStage, StageStatus
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestWorkerAdapter:
    def test_coordinator_with_real_gen02_freezes_and_builds_context(
        self, engine: StorageEngine
    ) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        input_service = DefaultGenerationInputService(engine=engine)
        gateway = FakeSalesforceGatewayV2()
        req = make_request(job_id=job.canonical_job_id)
        gateway.records["Generation_Request__c"] = {
            req.salesforce_request_id: {"Id": req.salesforce_request_id, "Status__c": "Pending"}
        }
        projector = SalesforceRequestStateProjector(gateway=gateway, engine=engine)

        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=input_service,
        )

        engine.generation_requests.create_request(req)

        # Coordinate through context stage
        final_req, status, err = coordinator.process_request(
            req, stop_after_stage=GenerationStage.CONTEXT.value
        )
        assert err is None
        assert status == StageStatus.COMPLETED
        assert final_req.state == GenerationProcessing.RUNNING
        assert final_req.frozen_input_versions is not None

        # Verify durable freeze association in SQLite
        freeze_assoc = engine.generation_work.get_freeze_association(req.request_id)
        assert freeze_assoc is not None
        assert freeze_assoc.canonical_job_id == job.canonical_job_id

        # Verify durable context checkpoint in SQLite
        ctx_chk = engine.generation_work.get_checkpoint(req.request_id, GenerationStage.CONTEXT.value)
        assert ctx_chk is not None
        assert ctx_chk.status == StageStatus.COMPLETED

        # Verify durable context receipt in GEN-02 storage
        ctx_rec = engine.generation_inputs.get_context_receipt_by_request_id(req.request_id)
        assert ctx_rec is not None
        assert ctx_rec.result.bundle.posting_revision == job.revisions[0].content_hash

