"""Tests for observation replay, duplicate keys, and idempotent persistence (INGEST-01-S02)."""

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
    db_path = tmp_path / "data" / "sqlite" / "replay.db"
    raw_dir = tmp_path / "data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    engine.migrate()
    return engine


def test_replaying_identical_committed_page(storage: StorageEngine):
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    sink = DurableRawCaptureSink(storage.raw_dir)
    ref, c_hash = sink.capture(b'{"title": "DevOps"}', identifier_hint="devops_1")

    source_key = SourceKey(provider="prov_replay", board_id="board_replay", source_posting_id="devops_001")
    raw = RawPosting(
        raw_payload_ref=ref,
        raw_content_hash=c_hash,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"title": "DevOps"}',
    )

    receipt = PageReceipt(
        traversal_id="trav_rep",
        page_index=1,
        attempt_count=1,
        source_key="src_rep",
        scope_id="prov_replay_board_replay",
        adapter_name="test-v1",
        observed_posting_ids=["devops_001"],
        fetch_time=datetime.now(timezone.utc),
    )
    checkpoint = SourceCheckpoint(
        traversal_id="trav_rep",
        run_id=run_id,
        source_key="src_rep",
        scope_id="prov_replay_board_replay",
        adapter_name="test-v1",
        pages_completed=1,
        records_observed=["devops_001"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mgr = PagePersistenceManager(storage)

    # First commit
    mgr.commit_page(receipt, checkpoint, [raw])
    assert storage.raw_postings.get_raw_posting(source_key) is not None

    # Replay of identical commit should succeed idempotently
    mgr.commit_page(receipt, checkpoint, [raw])
    assert storage.raw_postings.get_raw_posting(source_key) is not None


def test_duplicate_posting_id_differing_content_handled(storage: StorageEngine):
    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    sink = DurableRawCaptureSink(storage.raw_dir)
    ref1, hash1 = sink.capture(b'{"title": "Original"}', identifier_hint="v1")
    ref2, hash2 = sink.capture(b'{"title": "Changed"}', identifier_hint="v2")

    source_key = SourceKey(provider="prov_diff", board_id="board_diff", source_posting_id="same_id_007")

    raw1 = RawPosting(
        raw_payload_ref=ref1,
        raw_content_hash=hash1,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"title": "Original"}',
    )
    raw2 = RawPosting(
        raw_payload_ref=ref2,
        raw_content_hash=hash2,
        source_key=source_key,
        fetch_time=datetime.now(timezone.utc),
        raw_payload='{"title": "Changed"}',
    )

    receipt1 = PageReceipt(
        traversal_id="trav_d1",
        page_index=1,
        attempt_count=1,
        source_key="src_d",
        scope_id="prov_diff_board_diff",
        adapter_name="test-v1",
        observed_posting_ids=["same_id_007"],
        fetch_time=datetime.now(timezone.utc),
    )
    chk1 = SourceCheckpoint(
        traversal_id="trav_d1",
        run_id=run_id,
        source_key="src_d",
        scope_id="prov_diff_board_diff",
        adapter_name="test-v1",
        pages_completed=1,
        records_observed=["same_id_007"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mgr = PagePersistenceManager(storage)
    # Commit first sighting
    mgr.commit_page(receipt1, chk1, [raw1])

    receipt2 = PageReceipt(
        traversal_id="trav_d2",
        page_index=2,
        attempt_count=1,
        source_key="src_d",
        scope_id="prov_diff_board_diff",
        adapter_name="test-v1",
        observed_posting_ids=["same_id_007"],
        fetch_time=datetime.now(timezone.utc),
    )
    chk2 = SourceCheckpoint(
        traversal_id="trav_d2",
        run_id=run_id,
        source_key="src_d",
        scope_id="prov_diff_board_diff",
        adapter_name="test-v1",
        pages_completed=2,
        records_observed=["same_id_007"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Commit changed content sighting for same ID: logs warning without raising exception
    mgr.commit_page(receipt2, chk2, [raw2])

    # Both payload files remain intact on disk
    assert sink.get(ref1) == b'{"title": "Original"}'
    assert sink.get(ref2) == b'{"title": "Changed"}'

