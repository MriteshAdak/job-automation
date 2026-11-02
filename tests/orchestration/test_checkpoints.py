"""Tests for stage checkpoints and work record persistence (RUN-01-S03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import PipelineStage
from job_automation.orchestration.checkpoints import CheckpointCoordinator
from job_automation.orchestration.records import StageWorkRecord, WorkItemState
from job_automation.storage.engine import StorageEngine


class TestCheckpoints:
    def test_stage_lifecycle_transitions(self, tmp_path: Path) -> None:
        db_path = tmp_path / "checkpoints.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)

        coord = CheckpointCoordinator(engine)
        coord.record_stage_start(run_id, "fetch")
        assert coord.get_stage_status(run_id, "fetch") == PipelineStage.RUNNING.value

        coord.record_stage_complete(run_id, "fetch", checkpoint_data={"count": 5})
        assert coord.get_stage_status(run_id, "fetch") == PipelineStage.SUCCEEDED.value

        engine.close()

    def test_granular_work_item_checkpoints(self, tmp_path: Path) -> None:
        db_path = tmp_path / "work.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        work = StageWorkRecord(
            run_id=run_id,
            attempt_id=attempt_id,
            stage_name="fetch",
            work_key="source:arbeitnow",
            input_fingerprint="fp_page_1",
            state=WorkItemState.RUNNING,
            checkpoint_data={"cursor": "cur_1", "pages_fetched": 1},
        )
        engine.pipeline_work.save_stage_work(work)

        retrieved = engine.pipeline_work.get_stage_work("fetch", "source:arbeitnow", "fp_page_1")
        assert retrieved is not None
        assert retrieved.checkpoint_data == {"cursor": "cur_1", "pages_fetched": 1}

        # Update checkpoint data
        coord = CheckpointCoordinator(engine)
        updated = coord.save_work_checkpoint(retrieved, {"cursor": "cur_2", "pages_fetched": 2})
        assert updated.checkpoint_data == {"cursor": "cur_2", "pages_fetched": 2}

        retrieved2 = engine.pipeline_work.get_stage_work("fetch", "source:arbeitnow", "fp_page_1")
        assert retrieved2 is not None
        assert retrieved2.checkpoint_data == {"cursor": "cur_2", "pages_fetched": 2}

        engine.close()

