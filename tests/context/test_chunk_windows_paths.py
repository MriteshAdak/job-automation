"""Tests for Windows path compatibility with spaces and German non-ASCII characters (CONTEXT-02-S07)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.context.chunk_serialization import (
    deserialize_chunk_set_from_json,
    serialize_chunk_set_to_json,
)
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


class TestChunkWindowsPaths:
    def test_chunk_serialization_and_disk_roundtrip_with_windows_unicode_path(
        self, tmp_path: Path
    ) -> None:
        # Path with spaces and German umlauts
        special_dir = tmp_path / "Bewerbung Prüfung" / "Chunks Daten & Berichte"
        special_dir.mkdir(parents=True, exist_ok=True)

        cid = uuid.uuid4()
        fid = uuid.uuid4()
        snap = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="prüfer@beispiel.de"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=fid,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Leitender Entwickler für Cloud-Systeme",
                    organization="Müller & Söhne IT GmbH",
                    start_date=PrecisionDate(value="2021-04", precision="month"),
                    claims=["Zuverlässige Skalierung auf über 500.000 Abfragen täglich"],
                    skills=["Python", "PostgreSQL"],
                    metrics=["99.99% Verfügbarkeit"],
                    provenance="zeugnis_müller.pdf",
                    allowed_uses=["assessment", "cv"],
                )
            ],
        )

        chunker = EvidenceChunker()
        manifest, err = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert err is None
        assert manifest is not None

        # Write manifest to special Windows path
        manifest_path = special_dir / "manifest_v1_prüfung.json"
        json_content = serialize_chunk_set_to_json(manifest)

        with open(manifest_path, "w", encoding="utf-8") as f:
            f.write(json_content)

        assert manifest_path.is_file()

        # Read back from special Windows path
        with open(manifest_path, "r", encoding="utf-8") as f:
            read_json = f.read()

        reloaded_manifest = deserialize_chunk_set_from_json(read_json)
        assert reloaded_manifest == manifest
        assert reloaded_manifest.manifest_fingerprint == manifest.manifest_fingerprint
        assert "Müller & Söhne IT GmbH" in reloaded_manifest.chunks[0].retrieval_text
