"""Unit tests for storage inventory scanning, reference graph, and protections (OPS-01-S01)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.contracts.primitives import SourceKey
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.records import ItemClass, ProtectionReason
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def test_engine_and_root(tmp_path: Path) -> tuple[StorageEngine, Path]:
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True)
    db_path = data_root / "database" / "job_automation.db"
    raw_dir = data_root / "raw"
    artifacts_dir = data_root / "artifacts"
    profiles_dir = data_root / "profiles"
    indexes_dir = data_root / "indexes"
    logs_dir = data_root / "logs"

    for d in (raw_dir, artifacts_dir, profiles_dir, indexes_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    engine = StorageEngine(
        db_path=db_path,
        raw_dir=raw_dir,
        artifacts_dir=artifacts_dir,
        profiles_dir=profiles_dir,
        indexes_dir=indexes_dir,
    )
    engine.migrate()
    return engine, data_root


def test_inventory_detects_referenced_raw_payloads(
    test_engine_and_root: tuple[StorageEngine, Path],
) -> None:
    engine, data_root = test_engine_and_root
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="post-100")

    # Save raw payload via filestore
    payload = json.dumps({"title": "Senior Python Developer", "company": "Tech Corp"})
    abs_path, content_hash = engine.filestore.save_raw_payload(
        provider=sk.provider,
        board_id=sk.board_id,
        source_posting_id=sk.source_posting_id,
        payload=payload,
    )

    # Save to database
    from job_automation.contracts.postings import RawPosting
    raw_posting = RawPosting(
        source_key=sk,
        raw_payload_ref=abs_path,
        raw_content_hash=content_hash,
        fetch_time=datetime.now(timezone.utc),
        raw_payload=payload,
    )
    engine.raw_postings.save_raw_posting(raw_posting)

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    assert inv.total_files_count >= 2  # database + raw payload
    raw_items = [it for it in inv.items if it.item_class == ItemClass.RAW_PAYLOAD]
    assert len(raw_items) == 1
    assert raw_items[0].is_referenced is True
    assert raw_items[0].is_protected is True
    assert ProtectionReason.REFERENCED_BY_RECORD in raw_items[0].protection_reasons


def test_inventory_detects_unreferenced_files(
    test_engine_and_root: tuple[StorageEngine, Path],
) -> None:
    engine, data_root = test_engine_and_root

    # Create unreferenced file in raw_dir
    unref_file = data_root / "raw" / "orphan" / "orphan.json"
    unref_file.parent.mkdir(parents=True, exist_ok=True)
    unref_file.write_text('{"orphan": true}', encoding="utf-8")

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    orphan_items = [it for it in inv.items if "orphan.json" in it.root_relative_path]
    assert len(orphan_items) == 1
    assert orphan_items[0].is_referenced is False


def test_inventory_deduplicates_shared_file_references(
    test_engine_and_root: tuple[StorageEngine, Path],
) -> None:
    engine, data_root = test_engine_and_root

    # Create one file referenced twice
    sample_file = data_root / "raw" / "shared.json"
    sample_file.write_text('{"shared": true}', encoding="utf-8")
    abs_path = str(sample_file.resolve())

    # Two raw postings pointing to the same file
    from job_automation.contracts.postings import RawPosting
    sk1 = SourceKey(provider="prov1", board_id="b1", source_posting_id="1")
    sk2 = SourceKey(provider="prov1", board_id="b1", source_posting_id="2")

    h = "sha256:" + "1" * 64
    engine.raw_postings.save_raw_posting(
        RawPosting(
            source_key=sk1,
            raw_payload_ref=abs_path,
            raw_content_hash=h,
            fetch_time=datetime.now(timezone.utc),
            raw_payload='{"shared": true}',
        )
    )
    engine.raw_postings.save_raw_posting(
        RawPosting(
            source_key=sk2,
            raw_payload_ref=abs_path,
            raw_content_hash=h,
            fetch_time=datetime.now(timezone.utc),
            raw_payload='{"shared": true}',
        )
    )

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    shared_items = [it for it in inv.items if "shared.json" in it.root_relative_path]
    assert len(shared_items) == 1
    assert len(shared_items[0].referencing_records) == 2


def test_inventory_protects_unfinished_work(
    test_engine_and_root: tuple[StorageEngine, Path],
) -> None:
    engine, data_root = test_engine_and_root

    # Insert a canonical job first to satisfy foreign keys
    from job_automation.contracts.identity import CanonicalJob
    job_id = uuid.uuid4()
    now_dt = datetime.now(timezone.utc)
    engine.canonical_jobs.save_canonical_job(
        CanonicalJob(
            canonical_job_id=job_id,
            company_name="Acme Corp",
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
    )

    req_id = uuid.uuid4()
    from job_automation.contracts.enums import GenerationProcessing
    from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest

    # Generation request in 'running' status
    req = GenerationRequest(
        request_id=req_id,
        canonical_job_id=job_id,
        document_type=DocumentType.CV,
        template_id="standard_cv",
        created_at=now_dt,
        state=GenerationProcessing.RUNNING,
        frozen_input_versions=FrozenInputVersions(
            posting_revision="rev-1",
            profile_version="1",
            policy_version="1",
            template_version="1",
        ),
    )
    engine.generation_requests.create_request(req)

    # Save an artifact associated with the generation request
    art_path, art_hash, art_size = engine.filestore.save_artifact_file(
        request_id=req_id,
        filename="CV.pdf",
        content=b"%PDF-1.4 dummy",
    )

    from job_automation.contracts.artifacts import Artifact
    art = Artifact(
        artifact_id=uuid.uuid4(),
        request_id=req_id,
        format="pdf",
        local_path=art_path,
        content_hash=art_hash,
        size_bytes=art_size,
        delivery_status="upload_pending",
        approval_status=DocumentApproval.DRAFT,
        created_at=now_dt,
    )
    engine.artifacts.save_artifact(art)

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    art_items = [it for it in inv.items if "CV.pdf" in it.root_relative_path]
    assert len(art_items) == 1
    assert art_items[0].is_protected is True
    assert ProtectionReason.UNFINISHED_WORK in art_items[0].protection_reasons


def test_transaction_participating_journal_rollback(
    test_engine_and_root: tuple[StorageEngine, Path],
) -> None:
    """Verifies Task 4: Injected failure rolls back inner journal writes cleanly."""
    engine, _ = test_engine_and_root
    plan_id = uuid.uuid4()
    journal_id = uuid.uuid4()

    # Outer transaction with injected failure
    with pytest.raises(RuntimeError, match="injected failure"):
        with engine.transaction():
            engine.operations.save_cleanup_plan(
                plan_id=plan_id,
                created_at="2026-10-29T10:00:00Z",
                expires_at="2026-10-30T10:00:00Z",
                store_fingerprint="fp1",
                policy_fingerprint="pfp1",
                plan_hash="h1",
                status="planned",
                plan_json="{}",
            )
            engine.operations.record_cleanup_journal_step(
                journal_id=journal_id,
                plan_id=plan_id,
                step_number=1,
                item_path="raw/test.json",
                stage="quarantined",
                status="in_progress",
            )
            raise RuntimeError("injected failure")

    # Verify both the plan and the journal write were rolled back!
    assert engine.operations.get_cleanup_plan(plan_id) is None
    assert len(engine.operations.get_cleanup_journal(plan_id)) == 0
