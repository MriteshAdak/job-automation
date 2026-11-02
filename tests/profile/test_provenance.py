"""Tests for provenance record creation, attestations, and documents."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from job_automation.profile.models import ProvenanceRecord
from job_automation.profile.provenance import create_provenance_record


class TestProvenance:
    def test_create_provenance_record_attestation(self) -> None:
        cid = uuid.uuid4()
        rec = create_provenance_record(
            candidate_id=cid,
            source_type="attestation",
            locator="Candidate confirmed via onboarding interview",
            notes="Direct verbal confirmation",
        )
        assert rec.candidate_id == cid
        assert rec.source_type == "attestation"
        assert rec.content_hash is None
        assert rec.file_path is None
        assert rec.locator == "Candidate confirmed via onboarding interview"

    def test_create_provenance_record_document(self) -> None:
        cid = uuid.uuid4()
        rec = create_provenance_record(
            candidate_id=cid,
            source_type="document",
            locator="Page 2, section 'Work Experience'",
            content_hash="sha256:1122334455667788",
            file_path="cid/contract.pdf",
        )
        assert rec.source_type == "document"
        assert rec.content_hash == "sha256:1122334455667788"
        assert rec.file_path == "cid/contract.pdf"

