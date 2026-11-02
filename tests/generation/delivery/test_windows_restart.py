"""Native Windows paths with spaces and umlauts, and crash-restart verification (GEN-06-S07)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest

from job_automation.generation.delivery_records import (
    DeliveryIntent,
    build_reconciliation_marker,
)
from job_automation.storage.engine import StorageEngine


def test_delivery_in_windows_path_with_spaces_and_umlauts(tmp_path: Path) -> None:
    # Directory path with spaces, umlauts, and special characters
    special_dir = tmp_path / "Bewerbung Prüfung äöü ÄÖÜ ß" / "Daten Größe"
    special_dir.mkdir(parents=True, exist_ok=True)

    db_path = special_dir / "delivery.sqlite"
    art_dir = special_dir / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)

    storage = StorageEngine(db_path=db_path, artifacts_dir=art_dir)
    storage.initialize_schema()

    req_id = uuid.uuid4()
    job_id = uuid.uuid4()
    art_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    storage.conn.execute(
        "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(job_id), "München Software AG", "active", "rev1", now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )
    storage.conn.execute(
        "INSERT INTO generation_requests (request_id, canonical_job_id, document_type, target_language, template_id, context_strategy, state, created_at, request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(req_id), str(job_id), "cv", "de", "content-basic", "full_json", "running", now.isoformat(), "{}"),
    )
    storage.conn.commit()

    marker = build_reconciliation_marker(req_id, art_id, 1)
    file_path = art_dir / "bewerbung_müller.docx"
    file_path.write_bytes(b"Test bytes for Windows Unicode path")

    intent = DeliveryIntent(
        intent_id=uuid.uuid4(),
        org_id="00D000000000001EAA",
        salesforce_request_id="a01000000000001AAA",
        canonical_salesforce_id="a00000000000001AAA",
        request_id=req_id,
        artifact_set_id=uuid.uuid4(),
        artifact_id=art_id,
        artifact_version=1,
        artifact_format="docx",
        content_hash="sha256:" + "f" * 64,
        size_bytes=len(b"Test bytes for Windows Unicode path"),
        local_path=str(file_path),
        reconciliation_marker=marker,
        status="pending",
        created_at=now,
        updated_at=now,
    )

    storage.artifact_deliveries.save_intent(intent)

    # Reopen in new storage connection simulating restart
    storage.close()

    storage_reopened = StorageEngine(db_path=db_path, artifacts_dir=art_dir)
    loaded = storage_reopened.artifact_deliveries.get_intent_by_marker("00D000000000001EAA", marker)
    assert loaded is not None
    assert loaded.local_path == str(file_path)
    assert Path(loaded.local_path).is_file()
    assert loaded.size_bytes == len(b"Test bytes for Windows Unicode path")
    storage_reopened.close()

