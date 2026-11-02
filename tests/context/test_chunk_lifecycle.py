"""End-to-end multi-version lifecycle verification for evidence chunking (CONTEXT-02-S07)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine
from tests.fakes.chunk_consumer import FakeIndexConsumer


class TestChunkLifecycle:
    def test_complete_multi_version_lifecycle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lifecycle_chunks.db"
        profiles_dir = tmp_path / "profiles"

        cid = uuid.uuid4()
        fid_emp = uuid.uuid4()
        fid_proj = uuid.uuid4()
        fid_skill = uuid.uuid4()
        fid_v2_new = uuid.uuid4()

        # =====================================================================
        # Phase 1: Intake and approve v1
        # =====================================================================
        with StorageEngine(db_path=db_path, profiles_dir=profiles_dir) as eng:
            eng.migrate()
            svc = ProfileService.from_engine(eng)

            draft1 = svc.import_draft(
                {
                    "candidate_id": str(cid),
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE"],
                        "target_locations": ["Berlin"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid_emp),
                            "kind": "employment",
                            "title": "Software Architect",
                            "organization": "Enterprise AG",
                            "start_date": {"value": "2020-01", "precision": "month"},
                            "end_date": {"value": "2023-05", "precision": "month"},
                            "skills": ["Python", "Docker"],
                            "claims": ["Led platform architecture"],
                            "provenance": "cert_2023.pdf",
                            "allowed_uses": ["assessment", "cv", "cover_letter"],
                        },
                        {
                            "fact_id": str(fid_proj),
                            "parent_id": str(fid_emp),
                            "kind": "project",
                            "title": "Cloud Migration",
                            "start_date": {"value": "2021", "precision": "year"},
                            "skills": ["AWS"],
                            "claims": ["Migrated monolith to microservices"],
                            "provenance": "report.pdf",
                            "allowed_uses": ["assessment", "cv", "cover_letter"],
                        },
                        {
                            "fact_id": str(fid_skill),
                            "kind": "skill",
                            "title": "Legacy Toolset",
                            "skills": ["Perl"],
                            "provenance": "old_cv.pdf",
                            "allowed_uses": ["cv"],  # only in CV
                        },
                    ],
                }
            )

            # Approve v1
            svc.approve_and_publish(
                draft_id=draft1.draft_id,
                expected_draft_digest=draft1.content_digest,
                approved_by="admin@example.com",
            )
            snap_v1 = svc.get_current_snapshot(cid)
            assert snap_v1 is not None
            assert snap_v1.profile_version == "v1"

            chunker = EvidenceChunker()

            # Build all three purposes
            cv_v1, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v1, purpose="cv"))
            assess_v1, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v1, purpose="assessment"))
            cov_v1, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v1, purpose="cover_letter"))

            assert cv_v1 is not None and assess_v1 is not None and cov_v1 is not None

            # CV has all 3 facts; assessment and cover_letter have 2 facts
            assert len(cv_v1.chunks) == 3
            assert len(assess_v1.chunks) == 2
            assert len(cov_v1.chunks) == 2

            # Consumer ingests v1 CV manifest
            consumer = FakeIndexConsumer()
            consumer.ingest_initial(cv_v1)
            assert len(consumer.list_chunk_ids()) == 3
            assert consumer.verify_active_binding(cid, "v1", "cv") is True

            # =====================================================================
            # Phase 2: Ingest and approve v2 (corrections, reparenting, permissions)
            # =====================================================================
            # In v2:
            # - fid_emp: title corrected to "Principal Software Architect", new skill "FastAPI"
            # - fid_proj: reparented (parent_id set to None), claims updated
            # - fid_skill: permission restricted to [] (removed from CV)
            # - fid_v2_new: added
            draft2 = svc.import_draft(
                {
                    "candidate_id": str(cid),
                    "base_profile_version": "v1",
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE"],
                        "target_locations": ["Berlin"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid_emp),
                            "kind": "employment",
                            "title": "Principal Software Architect",  # edited
                            "organization": "Enterprise AG",
                            "start_date": {"value": "2020-01", "precision": "month"},
                            "end_date": {"value": "2023-05", "precision": "month"},
                            "skills": ["Python", "Docker", "FastAPI"],  # edited
                            "claims": ["Led platform architecture"],
                            "provenance": "cert_2023.pdf",
                            "allowed_uses": ["assessment", "cv", "cover_letter"],
                        },
                        {
                            "fact_id": str(fid_proj),
                            "parent_id": None,  # reparented: no parent
                            "kind": "project",
                            "title": "Cloud Migration",
                            "start_date": {"value": "2021", "precision": "year"},
                            "skills": ["AWS"],
                            "claims": ["Migrated monolith to AWS EKS with zero downtime"],  # edited
                            "provenance": "report.pdf",
                            "allowed_uses": ["assessment", "cv", "cover_letter"],
                        },
                        {
                            "fact_id": str(fid_skill),
                            "kind": "skill",
                            "title": "Legacy Toolset",
                            "skills": ["Perl"],
                            "provenance": "old_cv.pdf",
                            "allowed_uses": [],  # restricted to private
                        },
                        {
                            "fact_id": str(fid_v2_new),
                            "kind": "award",
                            "title": "Speaker at CloudCon Berlin",
                            "provenance": "agenda.pdf",
                            "allowed_uses": ["cv"],  # new fact
                        },
                    ],
                }
            )

            svc.approve_and_publish(
                draft_id=draft2.draft_id,
                expected_draft_digest=draft2.content_digest,
                approved_by="admin@example.com",
                expected_base_version="v1",
            )
            snap_v2 = svc.get_current_snapshot(cid)
            assert snap_v2 is not None
            assert snap_v2.profile_version == "v2"

            cv_v2, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v2, purpose="cv"))
            assert cv_v2 is not None

            # Compare v1 and v2 CV manifests
            diff, err = chunker.diff(cv_v1, cv_v2)
            assert err is None
            assert diff is not None
            assert diff.replacement_required is True

            # Identify chunk IDs
            v1_map = {c.primary_fact_id: c.chunk_id for c in cv_v1.chunks}
            v2_map = {c.primary_fact_id: c.chunk_id for c in cv_v2.chunks}

            # fid_skill was restricted -> removed from CV
            assert v1_map[fid_skill] in diff.removed_chunk_ids
            # fid_v2_new added
            assert v2_map[fid_v2_new] in diff.added_chunk_ids
            # fid_emp content updated
            assert v2_map[fid_emp] in diff.content_changed_chunk_ids
            # fid_proj reparented
            assert v2_map[fid_proj] in diff.content_changed_chunk_ids

            # Apply change set to consumer
            consumer.apply_change_set(diff, cv_v2)
            assert consumer.verify_active_binding(cid, "v2", "cv") is True
            assert consumer.verify_active_binding(cid, "v1", "cv") is False

            # Removed chunk is absent from consumer
            assert consumer.get_chunk(v1_map[fid_skill]) is None

            # Updated chunk has new title
            emp_chunk = consumer.get_chunk(v2_map[fid_emp])
            assert emp_chunk is not None
            assert emp_chunk.title == "Principal Software Architect"

            # =====================================================================
            # Phase 3: Historical C08 resolution remains permanently possible
            # =====================================================================
            # Historical C08 citation to v1 fact resolves cleanly
            c08_v1_emp = CandidateEvidenceReference(profile_version="v1", fact_id=fid_emp)
            resolved_v1 = svc.resolve_candidate_reference(c08_v1_emp)
            assert resolved_v1 is not None
            assert resolved_v1.title == "Software Architect"

            # Historical C08 citation to v1 restricted fact also resolves for audit
            c08_v1_skill = CandidateEvidenceReference(profile_version="v1", fact_id=fid_skill)
            resolved_v1_skill = svc.resolve_candidate_reference(c08_v1_skill)
            assert resolved_v1_skill is not None
            assert resolved_v1_skill.title == "Legacy Toolset"

            # But consumer rejects stale v1 manifest for v2 requests
            valid, bind_err = chunker.validate_binding(
                cv_v1,
                expected_candidate_id=cid,
                expected_profile_version="v2",
                expected_purpose="cv",
            )
            assert valid is False
            assert bind_err is not None
