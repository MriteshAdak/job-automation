"""Tests verifying crash recovery and reopen across separate Python processes (GEN-05-S07)."""
from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest


def test_cross_process_reopen_and_verification(tmp_path: Path) -> None:
    """Render in Process 1, shut down, and reopen & verify bytes in Process 2."""
    db_path = tmp_path / "cross_proc.sqlite"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    req_id = str(uuid.uuid4())

    # Script for Process 1: Setup and render
    proc1_code = f"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from job_automation.storage.engine import StorageEngine
from job_automation.generation.render_service import RenderService
from job_automation.generation.validation_records import ValidatedDraftForRendering
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.contracts.enums import DocumentType
from tests.generation.rendering.test_docx_renderer import _build_test_draft

db_path = Path(r"{db_path}")
artifacts_dir = Path(r"{artifacts_dir}")
engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
engine.initialize_schema()

req_id = uuid.UUID("{req_id}")
job_id = uuid.uuid4()
now = datetime.now(timezone.utc)

engine.conn.execute(
    "INSERT INTO canonical_jobs (canonical_job_id, company_name, availability, current_revision_id, first_seen_at, last_seen_at, job_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (str(job_id), "Proc Corp", "active", "rev1", now.isoformat(), now.isoformat(), "{{}}", now.isoformat(), now.isoformat()),
)
engine.conn.execute(
    "INSERT INTO generation_requests (request_id, canonical_job_id, document_type, target_language, template_id, context_strategy, state, created_at, request_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    (str(req_id), str(job_id), "cv", "de", "content-basic", "full_json", "running", now.isoformat(), "{{}}"),
)

draft = _build_test_draft(doc_type=DocumentType.CV, language="de", request_id=req_id)
draft_hash = compute_sha256_digest(draft)

envelope = ValidatedDraftForRendering(
    draft=draft,
    draft_hash=draft_hash,
    report_id=uuid.uuid4(),
    report_hash="sha256:" + "a" * 64,
    binding_hash="sha256:" + "b" * 64,
    content_spec_id="2.0",
    render_decision="allowed_for_review",
    requires_human_review=True,
    review_warnings=[],
)

service = RenderService(engine)
res = service.render_or_reopen(envelope, requested_formats=["docx"])
assert res.status == "completed", f"Render failed: {{res.error}}"
engine.close()
print("PROCESS1_SUCCESS")
"""

    res1 = subprocess.run(
        [sys.executable, "-c", proc1_code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res1.returncode == 0, f"Process 1 failed:\nSTDOUT:\n{res1.stdout}\nSTDERR:\n{res1.stderr}"
    assert "PROCESS1_SUCCESS" in res1.stdout

    # Script for Process 2: Start fresh, open database, and verify saved artifact set
    proc2_code = f"""
import uuid
from pathlib import Path
from job_automation.storage.engine import StorageEngine
from job_automation.generation.render_service import RenderService

db_path = Path(r"{db_path}")
artifacts_dir = Path(r"{artifacts_dir}")
engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)

req_id = uuid.UUID("{req_id}")
service = RenderService(engine)
reopened = service.reopen_artifact_set(req_id, version=1)

assert reopened.status == "completed", f"Reopen failed: {{reopened.error}}"
assert reopened.artifact_set is not None
assert "docx" in reopened.artifact_set.artifacts

rcpt = reopened.artifact_set.artifacts["docx"]
docx_path = Path(rcpt.local_path)
assert docx_path.is_file(), f"File missing: {{docx_path}}"
assert docx_path.stat().st_size == rcpt.size_bytes

engine.close()
print("PROCESS2_SUCCESS")
"""

    res2 = subprocess.run(
        [sys.executable, "-c", proc2_code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res2.returncode == 0, f"Process 2 failed:\nSTDOUT:\n{res2.stdout}\nSTDERR:\n{res2.stderr}"
    assert "PROCESS2_SUCCESS" in res2.stdout

