"""Tests for crash recovery and unfinished record preservation upon process restart."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    GenerationProcessing,
    PipelineStage,
    PostingAvailability,
    RunStatus,
    SyncOperationState,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.storage.engine import StorageEngine


class TestRecovery:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "recovery_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_interrupted_run_and_stages_recovery(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id, status="running")

        # Record stage 1: succeeded
        engine.runs.record_stage(
            run_id=run_id,
            stage_name="fetch",
            status=PipelineStage.SUCCEEDED,
            completed_at=datetime.now(timezone.utc),
        )

        # Record stage 2: running when crash occurred
        engine.runs.record_stage(
            run_id=run_id,
            stage_name="normalize",
            status=PipelineStage.RUNNING,
        )

        # Verify unfinished records are detected
        unfinished_runs = engine.runs.get_unfinished_runs()
        assert len(unfinished_runs) == 1
        assert unfinished_runs[0]["run_id"] == str(run_id)

        unfinished_stages = engine.runs.get_unfinished_stages(run_id=run_id)
        assert len(unfinished_stages) == 1
        assert unfinished_stages[0]["stage_name"] == "normalize"

        # Recover interrupted run
        recovered_count = engine.runs.recover_interrupted_runs(
            failure_reason="Process crash before pipeline completion"
        )
        assert recovered_count == 1

        # Unfinished runs list should now be clean
        assert len(engine.runs.get_unfinished_runs()) == 0
        assert len(engine.runs.get_unfinished_stages(run_id=run_id)) == 0

        # Run summary should report FAILED status
        run = engine.runs.get_run(run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert run.end_time is not None

        # Normalize stage should be marked failed with classified error
        stages = engine.runs.get_stages(run_id)
        norm_stage = next(s for s in stages if s["stage_name"] == "normalize")
        assert norm_stage["status"] == PipelineStage.FAILED.value
        assert norm_stage["error"] is not None
        assert "Process crash" in norm_stage["error"].message

    def test_checkpoint_resumption_across_restart(self, engine: StorageEngine) -> None:
        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)

        # Save checkpoint during fetch stage
        engine.runs.save_checkpoint(
            run_id=run_id,
            stage_name="fetch",
            checkpoint_key="pagination",
            data={"page": 3, "cursor": "csr_xyz789", "items_seen": 75},
        )

        # Close and reopen to simulate process restart
        engine.close()
        new_engine = StorageEngine(db_path=engine.db_path)
        try:
            # Reopened process resumes and reads checkpoint
            checkpoint = new_engine.runs.get_checkpoint(run_id, "fetch", "pagination")
            assert checkpoint is not None
            assert checkpoint["page"] == 3
            assert checkpoint["cursor"] == "csr_xyz789"
            assert checkpoint["items_seen"] == 75
        finally:
            new_engine.close()

    def test_unfinished_sync_operations_recovery(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Dev",
            company_name="Acme Corp",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition="eligible",
            assessment_reasons="Qualified",
            last_evaluated_at=now_dt,
        )

        # Operation 1: pending
        op1 = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=job_id,
            payload_version="v1",
            payload_fingerprint="sha256:1111111111111111111111111111111111111111111111111111111111111111",
            locally_owned_payload=payload,
            state=SyncOperationState.PENDING,
        )
        # Operation 2: running (crashed while sending)
        op2 = SyncOperation(
            operation_id=uuid.uuid4(),
            canonical_job_id=job_id,
            payload_version="v2",
            payload_fingerprint="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            locally_owned_payload=payload,
            state=SyncOperationState.RUNNING,
        )
        engine.sync_outbox.enqueue_operation(op1)
        engine.sync_outbox.enqueue_operation(op2)

        # Unfinished operations must find both
        unfinished = engine.sync_outbox.get_unfinished_operations()
        assert len(unfinished) == 2

        # Stale running recovery resets op2 to retry_wait
        recovered = engine.sync_outbox.recover_stale_running()
        assert len(recovered) == 1
        assert recovered[0].operation_id == op2.operation_id

        # op2 in storage is now RETRY_WAIT
        saved_op2 = engine.sync_outbox.get_operation(op2.operation_id)
        assert saved_op2 is not None
        assert saved_op2.state == SyncOperationState.RETRY_WAIT

    def test_unfinished_generation_requests_recovery(self, engine: StorageEngine) -> None:
        job_id = uuid.uuid4()
        now_dt = datetime.now(timezone.utc)
        job = CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

        # Create request and claim it (moves to RUNNING with frozen inputs)
        req_id = uuid.uuid4()
        req = GenerationRequest(
            request_id=req_id,
            canonical_job_id=job_id,
            document_type="cv",
            template_id="standard_cv",
            created_at=now_dt,
        )
        engine.generation_requests.create_request(req)

        frozen = FrozenInputVersions(
            posting_revision="sha256:aaaa",
            profile_version="1.0",
            policy_version="1.0",
            template_version="1.0",
        )
        engine.generation_requests.claim_request(req_id, frozen)

        # Verify request is returned in unfinished
        unfinished = engine.generation_requests.get_unfinished_requests()
        assert len(unfinished) == 1
        assert unfinished[0].request_id == req_id
        assert unfinished[0].state == GenerationProcessing.RUNNING

        # Simulate recovery
        recovered_count = engine.generation_requests.recover_interrupted_requests(
            reason="Worker interrupted mid-generation"
        )
        assert recovered_count == 1

        # Request is now FAILED with recoverable error
        recovered_req = engine.generation_requests.get_request(req_id)
        assert recovered_req is not None
        assert recovered_req.state == GenerationProcessing.FAILED
        assert recovered_req.error is not None
        assert "Worker interrupted mid-generation" in recovered_req.error.message

