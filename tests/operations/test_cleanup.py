"""Unit tests for safe cleanup application under maintenance lock (OPS-01-S04)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.primitives import SourceKey
from job_automation.operations.cleanup import apply_cleanup
from job_automation.operations.exceptions import OperationsError, PlanInvalidatedError
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.preview import generate_cleanup_preview
from job_automation.operations.records import OperationStatus, OperationsSettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def sample_setup(tmp_path: Path) -> tuple[StorageEngine, Path]:
    data_root = tmp_path / "data"
    data_root.mkdir()
    db_path = data_root / "database" / "job_automation.db"
    raw_dir = data_root / "raw"
    artifacts_dir = data_root / "artifacts"
    profiles_dir = data_root / "profiles"
    indexes_dir = data_root / "indexes"

    for d in (raw_dir, artifacts_dir, profiles_dir, indexes_dir):
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


def test_apply_cleanup_success(sample_setup: tuple[StorageEngine, Path]) -> None:
    engine, data_root = sample_setup

    # Create unreferenced file
    orphan = data_root / "raw" / "orphan.json"
    orphan.write_text('{"old_unreferenced": true}', encoding="utf-8")
    orphan_bytes = len(orphan.read_bytes())

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    future_cutoff = datetime.now(timezone.utc) + timedelta(days=100)
    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})

    plan = generate_cleanup_preview(
        inventory=inv,
        settings=settings,
        engine=engine,
        cutoff_time=future_cutoff,
    )

    # Apply cleanup
    result = apply_cleanup(
        plan_id=plan.plan_id,
        plan_hash=plan.plan_hash,
        settings=settings,
        data_root=data_root,
        engine=engine,
    )

    assert result.status == OperationStatus.SUCCEEDED
    assert result.deleted_count == 1
    assert result.actual_reclaimed_bytes == orphan_bytes
    assert not orphan.exists()

    # Verify plan marked applied
    saved = engine.operations.get_cleanup_plan(plan.plan_id)
    assert saved is not None
    assert saved["status"] == "applied"

    # Verify journal recorded steps
    journal = engine.operations.get_cleanup_journal(plan.plan_id)
    assert len(journal) >= 2  # quarantined + deleted


def test_apply_cleanup_rejects_plan_if_candidate_becomes_referenced(
    sample_setup: tuple[StorageEngine, Path],
) -> None:
    engine, data_root = sample_setup

    # Create unreferenced file
    orphan = data_root / "raw" / "becoming_referenced.json"
    orphan.write_text('{"data": 1}', encoding="utf-8")

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    future_cutoff = datetime.now(timezone.utc) + timedelta(days=100)
    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})

    plan = generate_cleanup_preview(
        inventory=inv,
        settings=settings,
        engine=engine,
        cutoff_time=future_cutoff,
    )

    # Now simulate a race: another worker references this file before apply!
    from job_automation.contracts.postings import RawPosting
    from job_automation.storage.filestore import compute_sha256
    sk = SourceKey(provider="arbeitnow", board_id="default", source_posting_id="newly-referenced")
    engine.raw_postings.save_raw_posting(
        RawPosting(
            source_key=sk,
            raw_payload_ref=str(orphan.resolve()),
            raw_content_hash=compute_sha256(orphan.read_bytes()),
            fetch_time=datetime.now(timezone.utc),
            raw_payload='{"data": 1}',
        )
    )

    # Apply cleanup should ABORT to prevent deleting referenced data!
    with pytest.raises(PlanInvalidatedError, match="Plan invalidated"):
        apply_cleanup(
            plan_id=plan.plan_id,
            plan_hash=plan.plan_hash,
            settings=settings,
            data_root=data_root,
            engine=engine,
        )

    # Candidate file must remain INTACT
    assert orphan.exists()


def test_apply_cleanup_rejects_wrong_hash(sample_setup: tuple[StorageEngine, Path]) -> None:
    engine, data_root = sample_setup

    orphan = data_root / "raw" / "orphan.json"
    orphan.write_text('{}')

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})
    plan = generate_cleanup_preview(
        inventory=inv,
        settings=settings,
        engine=engine,
        cutoff_time=datetime.now(timezone.utc) + timedelta(days=100),
    )

    with pytest.raises(OperationsError, match="Supplied plan hash"):
        apply_cleanup(
            plan_id=plan.plan_id,
            plan_hash="bad_hash",
            settings=settings,
            data_root=data_root,
            engine=engine,
        )
