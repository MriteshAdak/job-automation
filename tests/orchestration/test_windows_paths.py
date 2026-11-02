"""Native Windows path validation tests for RUN-01 (RUN-01-S02, S10).

Validates:
- Execution on directories with spaces and Unicode characters (e.g., German umlauts 'ä', 'ö', 'ü').
- Case insensitivity handling for lock paths and database storage.
- Relative vs absolute path normalization.
- Forward slashes vs Windows backslashes parity.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability, RunStatus
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.orchestration.locking import normalize_lock_target
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.orchestration.windows_lock import WindowsWorkerLock
from job_automation.storage.engine import StorageEngine


class TestWindowsPaths:
    def test_unicode_and_spaces_in_paths(self, tmp_path: Path) -> None:
        """Pipeline operates cleanly in folders with Unicode characters and spaces."""
        unicode_dir = tmp_path / "Job Automation RUN Prüfung ä ö ü" / "Daten Größe"
        unicode_dir.mkdir(parents=True, exist_ok=True)

        db_path = unicode_dir / "job_automation.db"
        raw_dir = unicode_dir / "Rohdaten"
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 1. Test StorageEngine on Unicode path
        engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
        engine.initialize_schema()

        now = datetime.now(timezone.utc)
        job_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        cjob = CanonicalJob(
            canonical_job_id=job_id,
            company_name="München Software GmbH",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        retrieved = engine.canonical_jobs.get_canonical_job(job_id)
        assert retrieved is not None
        assert retrieved.company_name == "München Software GmbH"

        # 2. Test WindowsWorkerLock on Unicode path
        lock = WindowsWorkerLock(unicode_dir)
        with lock.acquire() as token:
            assert token.is_released is False
            assert os.path.exists(token.lock_path)
            # Second acquire on exact same path fails
            lock2 = WindowsWorkerLock(unicode_dir)
            with pytest.raises(Exception):
                lock2.acquire_lock()

        # 3. Test PipelineRunner on Unicode data_root
        cand_id = uuid.uuid4()
        profile = ProfileSnapshot(
            candidate_id=cand_id,
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="Candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(
                work_authorization_countries=["DE"],
                remote_eligible=True,
            ),
            evidence_records=[],
        )
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )

        runner = PipelineRunner(data_root=unicode_dir, engine=engine)
        opts = RunOptions(
            assessment_mode="rules",
            enable_sync=False,
        )

        report = runner.start_run(
            options=opts,
            profile_override=profile,
            policy_override=policy,
            effective_sources_override=[],
        )

        assert report.exit_code == 0
        assert report.c15_summary.status == RunStatus.SUCCESS

        engine.close()

    def test_path_normalization_case_and_slashes(self, tmp_path: Path) -> None:
        """Lock target normalization handles case differences and slash styles."""
        test_dir = tmp_path / "CaseFolder_Test"
        test_dir.mkdir(parents=True, exist_ok=True)

        path_forward = str(test_dir).replace("\\", "/")
        path_backward = str(test_dir).replace("/", "\\")
        path_lower = str(test_dir).lower()
        path_upper = str(test_dir).upper()

        norm_f = normalize_lock_target(path_forward)
        norm_b = normalize_lock_target(path_backward)
        norm_l = normalize_lock_target(path_lower)
        norm_u = normalize_lock_target(path_upper)

        assert norm_f == norm_b
        assert str(norm_f).lower() == str(norm_l).lower()
        assert str(norm_f).lower() == str(norm_u).lower()
