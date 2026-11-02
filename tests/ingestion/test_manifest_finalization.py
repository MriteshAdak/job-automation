"""Tests for idempotent C04 FetchManifest finalization (INGEST-01-S07)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import FetchOutcome, InventorySemantics
from job_automation.contracts.postings import FetchManifest
from job_automation.ingestion.manifests import finalize_manifest
from job_automation.storage.engine import StorageEngine


def test_idempotent_manifest_finalization(tmp_path: Path):
    db_path = tmp_path / "fin" / "data.db"
    raw_dir = tmp_path / "fin" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    storage.migrate()

    run_id = uuid.uuid4()
    storage.runs.create_run(run_id=run_id)

    now = datetime.now(timezone.utc)
    manifest1 = FetchManifest(
        run_id=run_id,
        source_key="src_idempotent",
        scope_id="prov_board",
        start_time=now,
        end_time=now,
        cursor_in=None,
        cursor_out="cont-v1:abc",
        page_count=1,
        raw_response_refs=["raw://1"],
        observed_posting_identities=["id_1"],
        outcome=FetchOutcome.PARTIAL,
        inventory_semantics=InventorySemantics.FILTERED_FEED,
    )

    # First finalization
    fin1 = finalize_manifest(storage, manifest1)
    stored1 = storage.raw_postings.get_manifests_for_run(run_id)
    assert len(stored1) == 1
    assert stored1[0].outcome == FetchOutcome.PARTIAL

    # Updated finalization (e.g. on resume completion)
    manifest2 = FetchManifest(
        run_id=run_id,
        source_key="src_idempotent",
        scope_id="prov_board",
        start_time=now,
        end_time=now,
        cursor_in=None,
        cursor_out=None,
        page_count=2,
        raw_response_refs=["raw://1", "raw://2"],
        observed_posting_identities=["id_1", "id_2"],
        outcome=FetchOutcome.COMPLETE,
        inventory_semantics=InventorySemantics.FILTERED_FEED,
    )
    fin2 = finalize_manifest(storage, manifest2)

    stored2 = storage.raw_postings.get_manifests_for_run(run_id)
    # Exactly ONE authoritative manifest exists per (run_id, source_key, scope_id)
    assert len(stored2) == 1
    assert stored2[0].outcome == FetchOutcome.COMPLETE
    assert stored2[0].page_count == 2
    assert stored2[0].observed_posting_identities == ["id_1", "id_2"]

