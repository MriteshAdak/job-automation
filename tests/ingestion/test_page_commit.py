"""Tests for durable atomic page commits and rollback (INGEST-01-S02)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.adapter_results import Continuation
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.models import PageReceipt, SourceCheckpoint
from job_automation.ingestion.persistence import PagePersistenceManager
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def storage(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "data" / "sqlite" / "test.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    engine.migrate()
    return engine


def test_atomic_page_commit_success(storage: StorageEngine):
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    sink = DurableRawCaptureSink(storage.raw_dir)
    ref, c_hash = sink.capture(b'{"title": "Engineer"}', identifier_hint="test_1")

    source_key = SourceKey(provider="prov1", board_id="board1", source_posting_id="post_001")
    raw = RawPosting(
        raw_payload_ref=ref,
        raw_content_hash=c_hash,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"title": "Engineer"}',
    )

    cont = Continuation(
        kind="page",
        value="2",
        source_key="prov1_src",
        scope_id="prov1_board1",
        adapter_name="test-v1",
    )
    receipt = PageReceipt(
        traversal_id="trav_1",
        page_index=1,
        attempt_count=1,
        continuation_in=None,
        continuation_out=cont,
        source_key="prov1_src",
        scope_id="prov1_board1",
        adapter_name="test-v1",
        raw_response_refs=[ref],
        raw_response_hashes=[c_hash],
        observed_posting_ids=["post_001"],
        raw_record_refs=[ref],
        fetch_time=datetime.now(timezone.utc),
        exhausted=False,
    )
    checkpoint = SourceCheckpoint(
        traversal_id="trav_1",
        run_id=run_id,
        source_key="prov1_src",
        scope_id="prov1_board1",
        adapter_name="test-v1",
        current_continuation=cont,
        visited_tokens=[],
        pages_completed=1,
        records_observed=["post_001"],
        raw_response_refs=[ref],
        requests_made=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mgr = PagePersistenceManager(storage)
    mgr.commit_page(receipt, checkpoint, [raw])

    # Verify raw posting was committed
    fetched_raw = storage.raw_postings.get_raw_posting(source_key)
    assert fetched_raw is not None
    assert fetched_raw.source_key == source_key
    assert fetched_raw.raw_content_hash == c_hash

    # Verify checkpoint was committed
    loaded_chk = mgr.load_checkpoint(run_id, "prov1_src", "prov1_board1")
    assert loaded_chk is not None
    assert loaded_chk.pages_completed == 1
    assert loaded_chk.records_observed == ["post_001"]


def test_atomic_page_commit_fault_injection_rollback(storage: StorageEngine):
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    sink = DurableRawCaptureSink(storage.raw_dir)
    ref, c_hash = sink.capture(b'{"title": "Engineer"}', identifier_hint="test_fail")

    source_key = SourceKey(provider="prov_fail", board_id="board_fail", source_posting_id="post_fail_01")
    raw = RawPosting(
        raw_payload_ref=ref,
        raw_content_hash=c_hash,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"title": "Engineer"}',
    )

    receipt = PageReceipt(
        traversal_id="trav_fail",
        page_index=1,
        attempt_count=1,
        source_key="src_fail",
        scope_id="prov_fail_board_fail",
        adapter_name="test-v1",
        observed_posting_ids=["post_fail_01"],
        fetch_time=datetime.now(timezone.utc),
    )
    # Checkpoint references a NON-EXISTENT run_id to trigger SQLite foreign key violation
    non_existent_run_id = uuid.uuid4()
    checkpoint = SourceCheckpoint(
        traversal_id="trav_fail",
        run_id=non_existent_run_id,
        source_key="src_fail",
        scope_id="prov_fail_board_fail",
        adapter_name="test-v1",
        pages_completed=1,
        records_observed=["post_fail_01"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mgr = PagePersistenceManager(storage)

    import sqlite3
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        mgr.commit_page(receipt, checkpoint, [raw])

    # Verify rollback: raw posting was NOT committed
    fetched_raw = storage.raw_postings.get_raw_posting(source_key)
    assert fetched_raw is None

    # Verify checkpoint was NOT committed
    loaded_chk = mgr.load_checkpoint(non_existent_run_id, "src_fail", "prov_fail_board_fail")
    assert loaded_chk is None
