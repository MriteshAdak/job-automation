"""Tests for multi-source runtime failure isolation (RUN-01-S04)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from job_automation.contracts.enums import FetchOutcome
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.postings import FetchManifest, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import FetchStageResult, SourceFetchResult
from job_automation.orchestration.fetch_stage import FetchStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.storage.engine import StorageEngine


class TestSourceIsolation:
    def test_failed_source_does_not_cancel_successful_sources(self, tmp_path: Path) -> None:
        db_path = tmp_path / "iso.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(attempt)

        req = RunRequest(
            run_id=run_id,
            source_keys=["source_a", "source_b", "source_c"],
            app_config_hash="cfg_hash",
        )

        now = datetime.now(timezone.utc)
        sk_a = SourceKey(provider="prov_a", board_id="board_a", source_posting_id="1")
        sk_c = SourceKey(provider="prov_c", board_id="board_c", source_posting_id="2")

        draft_a = SourceJobDraft(
            source_key=sk_a,
            fetch_time=now,
            raw_reference="raw/a.json",
            original_fields={},
            source_mapped_fields={"title": "Role A"},
        )
        draft_c = SourceJobDraft(
            source_key=sk_c,
            fetch_time=now,
            raw_reference="raw/c.json",
            original_fields={},
            source_mapped_fields={"title": "Role C"},
        )

        from job_automation.contracts.enums import InventorySemantics

        man_a = FetchManifest(
            run_id=run_id,
            source_key="source_a",
            scope_id="prov_a_board_a",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/a.json"],
            observed_posting_identities=["1"],
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        man_b = FetchManifest(
            run_id=run_id,
            source_key="source_b",
            scope_id="prov_b_board_b",
            start_time=now,
            end_time=now,
            page_count=0,
            raw_response_refs=[],
            observed_posting_identities=[],
            outcome=FetchOutcome.FAILED,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
            error=ClassifiedError.from_category(ErrorCategory.TRANSIENT_NETWORK, "HTTP 500 error"),
        )
        man_c = FetchManifest(
            run_id=run_id,
            source_key="source_c",
            scope_id="prov_c_board_c",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/c.json"],
            observed_posting_identities=["2"],
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )

        from job_automation.contracts.adapter_results import DraftResult
        from job_automation.ingestion.models import PageReceipt

        dr_a = DraftResult(raw_reference="raw/a.json", draft=draft_a, issues=[])
        dr_c = DraftResult(raw_reference="raw/c.json", draft=draft_c, issues=[])

        receipt_a = PageReceipt(
            traversal_id=str(uuid.uuid4()),
            page_index=1,
            attempt_count=1,
            source_key="source_a",
            scope_id="prov_a_board_a",
            adapter_name="test",
            raw_response_refs=["raw/a.json"],
            raw_response_hashes=[f"sha256:{'a'*64}"],
            observed_posting_ids=["1"],
            raw_record_refs=["raw/a.json"],
            draft_results=[dr_a],
            issues=[],
            from_cache=False,
            fetch_time=now,
            exhausted=True,
            truncated=False,
        )
        receipt_c = PageReceipt(
            traversal_id=str(uuid.uuid4()),
            page_index=1,
            attempt_count=1,
            source_key="source_c",
            scope_id="prov_c_board_c",
            adapter_name="test",
            raw_response_refs=["raw/c.json"],
            raw_response_hashes=[f"sha256:{'c'*64}"],
            observed_posting_ids=["2"],
            raw_record_refs=["raw/c.json"],
            draft_results=[dr_c],
            issues=[],
            from_cache=False,
            fetch_time=now,
            exhausted=True,
            truncated=False,
        )

        stage_res = FetchStageResult(run_id=run_id)
        stage_res.sources_attempted = 3
        stage_res.sources_completed = 2
        stage_res.sources_failed = 1
        stage_res.total_raw_observations = 2
        stage_res.source_results = {
            "source_a": SourceFetchResult(
                source_key="source_a",
                outcome=FetchOutcome.COMPLETE,
                manifest=man_a,
                page_count=1,
                raw_records_count=1,
                observed_identities_count=1,
                accepted_drafts_count=1,
                rejected_records_count=0,
                warnings_count=0,
                requests_made=1,
                from_cache_count=0,
                receipts=[receipt_a],
            ),
            "source_b": SourceFetchResult(
                source_key="source_b",
                outcome=FetchOutcome.FAILED,
                manifest=man_b,
                page_count=0,
                raw_records_count=0,
                observed_identities_count=0,
                accepted_drafts_count=0,
                rejected_records_count=0,
                warnings_count=0,
                requests_made=1,
                from_cache_count=0,
                error=man_b.error,
                receipts=[],
            ),
            "source_c": SourceFetchResult(
                source_key="source_c",
                outcome=FetchOutcome.COMPLETE,
                manifest=man_c,
                page_count=1,
                raw_records_count=1,
                observed_identities_count=1,
                accepted_drafts_count=1,
                rejected_records_count=0,
                warnings_count=0,
                requests_made=1,
                from_cache_count=0,
                receipts=[receipt_c],
            ),
        }

        mock_controller = MagicMock(spec=FetchController)
        mock_controller.run_fetch.return_value = stage_res

        coord = FetchStageCoordinator(engine, mock_controller)
        res = coord.execute_fetch(req, attempt)

        assert res.sources_completed == 2
        assert res.sources_failed == 1
        assert len(res.drafts) == 2  # A and C drafts extracted!
        assert res.source_counts["source_a"] == 1
        assert res.source_counts["source_b"] == 0
        assert res.source_counts["source_c"] == 1

        # Check work records in database
        work_a = engine.pipeline_work.get_stage_work(
            "fetch", "source:source_a", "c6c5ad382fbfa0a7a37a5441e17d1211e0cb6d860d5b62b1ae446f777fb61c8c"
        )
        work_records = engine.pipeline_work.list_stage_work_for_run(run_id, "fetch")
        assert len(work_records) == 3
        status_map = {w.work_key: w.state.value for w in work_records}
        assert status_map["source:source_a"] == "completed"
        assert status_map["source:source_b"] == "failed"
        assert status_map["source:source_c"] == "completed"

        engine.close()
