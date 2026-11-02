"""Tests for process restart and storage reopen reproducibility (CONTEXT-02-S07)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.context.chunk_serialization import serialize_chunk_set_to_json
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine


class TestChunkWindowsRestart:
    def test_reopen_storage_and_rebuild_byte_reproducibility(self, tmp_path: Path) -> None:
        db_path = tmp_path / "restart_test.db"
        profiles_dir = tmp_path / "profiles"

        cid = uuid.uuid4()
        fid1 = uuid.uuid4()
        fid2 = uuid.uuid4()

        # Session 1: Create profile, approve, build chunks, record serialized manifest
        with StorageEngine(db_path=db_path, profiles_dir=profiles_dir) as eng1:
            eng1.migrate()
            svc1 = ProfileService.from_engine(eng1)

            draft = svc1.import_draft(
                {
                    "candidate_id": str(cid),
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE"],
                        "target_locations": ["Berlin"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid1),
                            "kind": "employment",
                            "title": "Principal Architect",
                            "organization": "Cloud GmbH",
                            "start_date": {"value": "2020-01", "precision": "month"},
                            "end_date": {"value": "2023-01", "precision": "month"},
                            "skills": ["Python", "Docker"],
                            "claims": ["Designed distributed event mesh"],
                            "provenance": "cert.pdf",
                            "allowed_uses": ["cv", "assessment"],
                        },
                        {
                            "fact_id": str(fid2),
                            "parent_id": str(fid1),
                            "kind": "project",
                            "title": "Kafka Gateway",
                            "skills": ["Kafka"],
                            "claims": ["Processed 5M events/day"],
                            "provenance": "log.pdf",
                            "allowed_uses": ["cv", "assessment"],
                        },
                    ],
                }
            )

            svc1.approve_and_publish(
                draft_id=draft.draft_id,
                expected_draft_digest=draft.content_digest,
                approved_by="lead@example.com",
            )
            snap1 = svc1.get_current_snapshot(cid)
            assert snap1 is not None

            chunker1 = EvidenceChunker()
            manifest1, _ = chunker1.build(ChunkBuildRequest(snapshot=snap1, purpose="cv"))
            assert manifest1 is not None
            serialized_session1 = serialize_chunk_set_to_json(manifest1)

        # Session 2: Fresh StorageEngine instance simulating new process
        with StorageEngine(db_path=db_path, profiles_dir=profiles_dir) as eng2:
            svc2 = ProfileService.from_engine(eng2)
            snap2 = svc2.get_current_snapshot(cid)
            assert snap2 is not None

            chunker2 = EvidenceChunker()
            manifest2, _ = chunker2.build(ChunkBuildRequest(snapshot=snap2, purpose="cv"))
            assert manifest2 is not None
            serialized_session2 = serialize_chunk_set_to_json(manifest2)

        # Byte-identical serialization and manifest fingerprints across restarts
        assert serialized_session1 == serialized_session2
        assert manifest1.manifest_fingerprint == manifest2.manifest_fingerprint
        assert [c.chunk_id for c in manifest1.chunks] == [c.chunk_id for c in manifest2.chunks]
        assert [c.chunk_version for c in manifest1.chunks] == [c.chunk_version for c in manifest2.chunks]
        assert [c.binding_fingerprint for c in manifest1.chunks] == [c.binding_fingerprint for c in manifest2.chunks]
