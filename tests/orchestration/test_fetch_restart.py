"""Tests for fetch stage restart across interrupted pagination (RUN-01-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.postings import FetchManifest, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import FetchStageResult, PageReceipt, SourceFetchResult
from job_automation.orchestration.fetch_stage import FetchStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.storage.engine import StorageEngine


class TestFetchRestart:
    def test_resume_preserves_committed_drafts(self, tmp_path: Path) -> None:
        db_path = tmp_path / "restart.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt1 = RunAttempt(run_id=run_id, attempt_sequence=1, status="interrupted")
        engine.pipeline_work.save_run_attempt(attempt1)
        attempt2 = RunAttempt(run_id=run_id, attempt_sequence=2, status="running")
        engine.pipeline_work.save_run_attempt(attempt2)

        req = RunRequest(
            run_id=run_id,
            source_keys=["arbeitnow"],
            app_config_hash="cfg_hash",
        )

        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="1")
        draft = SourceJobDraft(
            source_key=sk,
            fetch_time=now,
            raw_reference="raw/1.json",
            original_fields={},
            source_mapped_fields={"title": "Engineer"},
        )
        from job_automation.contracts.adapter_results import DraftResult
        from job_automation.contracts.enums import InventorySemantics
        dr = DraftResult(raw_reference="raw/1.json", draft=draft, issues=[])
        receipt = PageReceipt(
            traversal_id=str(uuid.uuid4()),
            page_index=1,
            attempt_count=1,
            source_key="arbeitnow",
            scope_id="arbeitnow_berlin",
            adapter_name="arbeitnow",
            raw_response_refs=["raw/1.json"],
            raw_response_hashes=[f"sha256:{'1'*64}"],
            observed_posting_ids=["1"],
            raw_record_refs=["raw/1.json"],
            draft_results=[dr],
            issues=[],
            from_cache=False,
            fetch_time=now,
            exhausted=True,
            truncated=False,
        )
        manifest = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow",
            scope_id="arbeitnow_berlin",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/1.json"],
            observed_posting_identities=["1"],
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        stage_res = FetchStageResult(run_id=run_id)
        stage_res.sources_attempted = 1
        stage_res.sources_completed = 1
        stage_res.total_raw_observations = 1
        stage_res.source_results = {
            "arbeitnow": SourceFetchResult(
                source_key="arbeitnow",
                outcome=FetchOutcome.COMPLETE,
                manifest=manifest,
                page_count=1,
                raw_records_count=1,
                observed_identities_count=1,
                accepted_drafts_count=1,
                rejected_records_count=0,
                warnings_count=0,
                requests_made=1,
                from_cache_count=0,
                receipts=[receipt],
            )
        }

        mock_controller = MagicMock(spec=FetchController)
        mock_controller.run_fetch.return_value = stage_res

        coord = FetchStageCoordinator(engine, mock_controller)
        res = coord.execute_fetch(req, attempt2)

        # Verified controller called with resume=True
        mock_controller.run_fetch.assert_called_once_with(
            run_id=run_id,
            source_keys=["arbeitnow"],
            resume=True,
        )
        assert len(res.drafts) == 1
        assert res.total_raw_observations == 1

        engine.close()
