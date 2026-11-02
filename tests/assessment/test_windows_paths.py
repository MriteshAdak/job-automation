"""Native Windows path and file handle verification tests (MATCH-01-S08).

Verifies that:
1. Assessment storage and evaluation work seamlessly with paths containing spaces and non-ASCII characters (e.g. German umlauts: ä, ö, ü).
2. SQLite connections cleanly release file locks on Windows so temporary databases can be deleted without WinError 32 (Sharing Violation).
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.assessment.inputs import bind_assessment_input
from job_automation.assessment.service import evaluate_deterministic
from job_automation.contracts.enums import AssessmentDisposition, WorkplaceType
from job_automation.contracts.identity import CanonicalJob
from job_automation.storage.engine import StorageEngine


class TestWindowsPaths:
    def test_storage_and_assessment_in_path_with_spaces_and_umlauts(
        self, make_posting, make_profile, make_policy
    ) -> None:
        # Create a folder in Windows TEMP with spaces and German umlauts
        base_temp = Path(os.environ.get("TEMP", "C:/Temp"))
        test_dir = base_temp / f"job_search_täst pfäd_{uuid.uuid4().hex[:8]}"
        test_dir.mkdir(parents=True, exist_ok=True)

        try:
            db_path = test_dir / "prüf_db.sqlite"
            raw_dir = test_dir / "roh daten"
            art_dir = test_dir / "artefäkte"

            engine = StorageEngine(db_path=db_path, raw_dir=raw_dir, artifacts_dir=art_dir)
            engine.initialize_schema()

            posting = make_posting(
                title="Softwareentwickler Python",
                country="DE",
                city="München",
                workplace_type=WorkplaceType.HYBRID,
            )
            profile = make_profile(auth_countries=["DE"])
            policy = make_policy(broad_keywords=["Python"])

            job_id = uuid.uuid4()
            now_dt = datetime.now(timezone.utc)
            job = CanonicalJob(
                canonical_job_id=job_id,
                company_name="Münchner Software Haus GmbH",
                current_revision_id=uuid.uuid4(),
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
            engine.canonical_jobs.save_canonical_job(job)

            inp = bind_assessment_input(
                canonical_job_id=job_id,
                posting_revision=posting.raw_content_hash,
                posting=posting,
                policy=policy,
                profile=profile,
            )

            assessment = evaluate_deterministic(inp)
            assert assessment.final_disposition == AssessmentDisposition.ELIGIBLE

            engine.assessments.save_assessment(assessment)
            loaded = engine.assessments.get_assessment(assessment.assessment_id)
            assert loaded is not None
            assert loaded.assessment_id == assessment.assessment_id

            # Crucial Windows check: close engine and verify file handle is released
            engine.close()

            # Verify file can be deleted without Windows sharing violation
            shutil.rmtree(test_dir)
            assert not test_dir.exists()

        finally:
            if test_dir.exists():
                try:
                    shutil.rmtree(test_dir)
                except Exception:
                    pass

