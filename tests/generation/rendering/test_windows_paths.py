"""Tests for native Windows filesystem paths with spaces and German unicode characters (GEN-05-S07)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.generation.input_records import compute_sha256_digest
from job_automation.generation.render_service import RenderService
from job_automation.generation.validation_records import ValidatedDraftForRendering
from job_automation.storage.engine import StorageEngine
from tests.generation.rendering.test_docx_renderer import _build_test_draft


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path) -> None:
    """Test full rendering and reopen lifecycle in a root directory with spaces and German umlauts."""
    root_with_umlauts = tmp_path / "Bewerbung Prüfung äöü ÄÖÜ ß" / "Unterlagen Größe"
    root_with_umlauts.mkdir(parents=True, exist_ok=True)

    db_path = root_with_umlauts / "datenbank.sqlite"
    artifacts_dir = root_with_umlauts / "artefakte speicher"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()

    now = datetime.now(timezone.utc)
    job_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    req_id = uuid.uuid4()

    engine.conn.execute(
        """
        INSERT INTO canonical_jobs (
            canonical_job_id, company_name, availability, current_revision_id,
            first_seen_at, last_seen_at, job_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(job_id), "München Software AG", "active", str(rev_id), now.isoformat(), now.isoformat(), "{}", now.isoformat(), now.isoformat()),
    )
    engine.conn.execute(
        """
        INSERT INTO generation_requests (
            request_id, canonical_job_id, document_type, target_language,
            template_id, context_strategy, state, created_at, request_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(req_id), str(job_id), "cv", "de", "content-basic", "full_json", "running", now.isoformat(), "{}"),
    )

    draft = _build_test_draft(
        doc_type=DocumentType.CV,
        language="de",
        request_id=req_id,
        claims_text=[
            "Prüfung bestanden für Qualitätsmanagement in München (äöü ÄÖÜ ß).",
            "Kosteneinsparungen von 25 % bei der Einführung neuer Geschäftsprozesse €.",
            "Zusammenarbeit mit Projektpartnern: „Erfolg durch Präzision“ – vorbildlich.",
        ],
    )
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

    assert res.status == "completed"
    assert res.artifact_set is not None
    assert "docx" in res.artifact_set.artifacts

    docx_receipt = res.artifact_set.artifacts["docx"]
    docx_file = Path(docx_receipt.local_path)
    assert docx_file.is_file()
    assert docx_file.stat().st_size > 0
    assert "Unterlagen Größe" in str(docx_file)

    # Reopen and verify from disk
    reopened = service.reopen_artifact_set(req_id, version=1)
    assert reopened.status == "completed"
    assert reopened.artifact_set is not None

    art = engine.artifacts.get_artifact(docx_receipt.artifact_id)
    assert art is not None
    assert art.delivery_status == "local_only"
    assert art.approval_status == DocumentApproval.DRAFT

    engine.close()

