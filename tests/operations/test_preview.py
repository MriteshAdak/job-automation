"""Unit tests for cleanup preview generation and plan immutability (OPS-01-S03)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.preview import compute_plan_hash, generate_cleanup_preview
from job_automation.operations.records import OperationsSettings
from job_automation.storage.engine import StorageEngine


@pytest.fixture
def sample_engine(tmp_path: Path) -> tuple[StorageEngine, Path]:
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


def test_preview_generation_non_destructive(sample_engine: tuple[StorageEngine, Path]) -> None:
    engine, data_root = sample_engine

    # Create unreferenced file
    orphan = data_root / "raw" / "orphan.json"
    orphan.write_text('{"unreferenced": true}', encoding="utf-8")

    mgr = RetentionInventoryManager(data_root)
    inv = mgr.build_inventory(engine)

    # Cutoff 100 days in the future to make orphan eligible
    future_cutoff = datetime.now(timezone.utc) + timedelta(days=100)
    settings = OperationsSettings(retention={"enabled": True, "raw_payloads_days": 90})

    plan = generate_cleanup_preview(
        inventory=inv,
        settings=settings,
        engine=engine,
        cutoff_time=future_cutoff,
    )

    # Verify preview exists and persisted
    assert len(plan.candidates) == 1
    assert plan.candidates[0].root_relative_path == "raw/orphan.json"
    assert plan.status == "planned"

    # Verify database persistence
    saved = engine.operations.get_cleanup_plan(plan.plan_id)
    assert saved is not None
    assert saved["plan_hash"] == plan.plan_hash

    # CRITICAL: Verify file on disk is NOT touched or deleted
    assert orphan.exists()
    assert orphan.read_text(encoding="utf-8") == '{"unreferenced": true}'


def test_plan_hash_determinism() -> None:
    h1 = compute_plan_hash("fp1", "pfp1", [{"root_relative_path": "a", "expected_hash": "1", "size_bytes": 10}])
    h2 = compute_plan_hash("fp1", "pfp1", [{"root_relative_path": "a", "expected_hash": "1", "size_bytes": 10}])
    h3 = compute_plan_hash("fp2", "pfp1", [{"root_relative_path": "a", "expected_hash": "1", "size_bytes": 10}])

    assert h1 == h2
    assert h1 != h3

