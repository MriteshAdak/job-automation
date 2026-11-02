"""Tests for fetch to normalize stage integration and quarantine handling (RUN-01-S04)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.postings import SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.normalization.service import DefaultNormalizer
from job_automation.orchestration.fetch_stage import FetchStageCoordinator
from job_automation.orchestration.normalize_stage import NormalizeStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.storage.engine import StorageEngine


class TestFetchNormalizeIntegration:
    def test_normalize_valid_and_quarantined_drafts(self, tmp_path: Path) -> None:
        db_path = tmp_path / "fn.db"
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(attempt)

        req = RunRequest(
            run_id=run_id,
            app_config_hash="cfg_hash",
        )

        normalizer = DefaultNormalizer()
        normalizer.register_raw_payload("raw/manual/good.json", b'{"raw": "payload"}')
        normalizer.register_raw_payload("raw/manual/bad.json", b'{"raw": "bad payload"}')
        norm_coord = NormalizeStageCoordinator(engine, normalizer)

        sk1 = SourceKey(provider="manual", board_id="berlin", source_posting_id="good_1")
        draft_valid = SourceJobDraft(
            source_key=sk1,
            fetch_time=datetime.now(timezone.utc),
            raw_reference="raw/manual/good.json",
            original_fields={"raw": "payload"},
            source_mapped_fields={
                "title": "Senior Python Engineer",
                "company_name_hint": "Acme Corp",
                "description": "Building great software.",
                "source_url": "https://acme.com/jobs/1",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        sk2 = SourceKey(provider="manual", board_id="berlin", source_posting_id="bad_1")
        # Missing title causes validation error -> quarantine
        draft_invalid = SourceJobDraft(
            source_key=sk2,
            fetch_time=datetime.now(timezone.utc),
            raw_reference="raw/manual/bad.json",
            original_fields={"raw": "payload"},
            source_mapped_fields={
                "company_name": "No Title Corp",
                "description": "Missing title entirely.",
                "source_url": "https://notitle.com/jobs/2",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        drafts = [
            (draft_valid, "raw/manual/good.json", 0),
            (draft_invalid, "raw/manual/bad.json", 1),
        ]

        result = norm_coord.execute_normalization(req, attempt, drafts)

        assert result.total_processed == 2
        assert len(result.normalized_postings) == 1
        assert result.normalized_postings[0].title == "Senior Python Engineer"
        assert result.quarantine_count == 1
        assert len(result.quarantine_records) == 1
        assert result.quarantine_records[0].source_key == sk2

        # Verify durable persistence in database
        saved_q = engine.pipeline_work.list_quarantine_records(run_id)
        assert len(saved_q) == 1
        assert saved_q[0].source_key == sk2
        assert any(i.field_path == "title" for i in saved_q[0].issues)

        engine.close()
