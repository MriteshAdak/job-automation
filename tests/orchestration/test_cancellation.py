"""Tests for controlled interruption and cancellation (RUN-01-S08)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from job_automation.contracts.enums import RunStatus
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.profile import CandidateEligibility, ProfileApprovalMetadata, ProfileSnapshot
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine


class TestCancellation:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "cancel_data" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    def test_keyboard_interrupt_handled_gracefully_and_releases_lock(
        self,
        tmp_path: Path,
        engine: StorageEngine,
    ) -> None:
        data_root = tmp_path / "cancel_data"
        now = datetime.now(timezone.utc)
        profile = ProfileSnapshot(
            candidate_id=uuid.uuid4(),
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="Candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(),
            evidence_records=[],
        )
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )

        runner = PipelineRunner(
            data_root=data_root,
            engine=engine,
        )

        opts = RunOptions(
            assessment_mode="rules",
            enable_sync=False,
        )

        # Mock FetchStageCoordinator.execute_fetch to simulate user pressing Ctrl+C (KeyboardInterrupt)
        with patch("job_automation.orchestration.runner.FetchStageCoordinator.execute_fetch") as mock_fetch:
            mock_fetch.side_effect = KeyboardInterrupt("Interrupted by user")

            report = runner.start_run(
                options=opts,
                profile_override=profile,
                policy_override=policy,
                effective_sources_override=[],
            )
            assert report.exit_code == 130
            assert report.c15_summary.status == RunStatus.PARTIAL

        # Verify lock was released cleanly: another worker lock can be acquired immediately!
        lock2 = WindowsWorkerLock(data_root)
        token2 = lock2.acquire_lock()
        assert token2 is not None
        token2.release()
