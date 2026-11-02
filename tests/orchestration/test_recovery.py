"""Tests for interrupted run inspection and recovery decisions (RUN-01-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import PipelineStage
from job_automation.orchestration.records import RunAttempt
from job_automation.orchestration.recovery import RecoveryManager
from job_automation.storage.engine import StorageEngine


class TestRecovery:
    def test_reconcile_initial_run(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rec.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        mgr = RecoveryManager(engine)
        plan = mgr.reconcile_interrupted_run(run_id)

        assert plan.next_attempt_sequence == 1
        assert plan.prior_attempt is None
        assert plan.reconciled_attempts == 0

        engine.close()

    def test_reconcile_crashed_attempt(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rec_crash.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)

        # Simulate crashed attempt 1 left in 'running' state
        attempt1 = RunAttempt(
            attempt_id=uuid.uuid4(),
            run_id=run_id,
            attempt_sequence=1,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        engine.pipeline_work.save_run_attempt(attempt1)
        engine.runs.record_stage(run_id, "fetch", PipelineStage.SUCCEEDED)
        engine.runs.record_stage(run_id, "normalize", PipelineStage.RUNNING)

        mgr = RecoveryManager(engine)
        plan = mgr.reconcile_interrupted_run(run_id)

        assert plan.reconciled_attempts == 1
        assert plan.prior_attempt is not None
        assert plan.prior_attempt.status == "interrupted"
        assert plan.prior_attempt.error is not None
        assert plan.next_attempt_sequence == 2
        assert "fetch" in plan.reusable_stages
        assert "normalize" in plan.resumable_stages

        # Verify persistent status in database
        latest = engine.pipeline_work.get_latest_attempt(run_id)
        assert latest is not None
        assert latest.status == "interrupted"

        engine.close()

    def test_create_new_attempt_increments_sequence(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rec_seq.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)

        mgr = RecoveryManager(engine)
        att1 = mgr.create_new_attempt(run_id, sequence=1)
        assert att1.attempt_sequence == 1

        att2 = mgr.create_new_attempt(run_id, sequence=2)
        assert att2.attempt_sequence == 2

        attempts = engine.pipeline_work.list_attempts(run_id)
        assert len(attempts) == 2
        assert [a.attempt_sequence for a in attempts] == [1, 2]

        engine.close()

