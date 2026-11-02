"""Tests for dependency-aware invalidation and manifest diffing (CONTEXT-02-S05)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_changes import compare_chunk_manifests
from job_automation.context.chunk_errors import ChunkValidationError
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import (
    ChunkBuildRequest,
    ChunkingSettings,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


class TestChunkInvalidation:
    def test_identical_manifest_comparison_yields_empty_change_set(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        fact = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Dev",
            provenance="ref",
            allowed_uses=["cv"],
        )
        snap = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact],
        )
        chunker = EvidenceChunker()
        manifest1, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        manifest2, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert manifest1 is not None and manifest2 is not None

        diff = compare_chunk_manifests(manifest1, manifest2)
        assert diff.replacement_required is False
        assert diff.added_chunk_ids == []
        assert diff.removed_chunk_ids == []
        assert diff.content_changed_chunk_ids == []
        assert diff.rebound_unchanged_chunk_ids == []
        assert "identical_manifest" in diff.reasons

    def test_invalidation_matrix_additions_removals_and_updates(self) -> None:
        cid = uuid.uuid4()
        f_keep_unchanged = uuid.uuid4()
        f_to_edit = uuid.uuid4()
        f_to_remove = uuid.uuid4()
        f_to_add = uuid.uuid4()

        # Snapshot v1: keep_unchanged, to_edit, to_remove
        facts_v1 = [
            CandidateFact(
                fact_id=f_keep_unchanged,
                kind=EvidenceFactKind.EDUCATION,
                title="B.Sc. CS",
                provenance="ref1",
                allowed_uses=["cv"],
            ),
            CandidateFact(
                fact_id=f_to_edit,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Junior Dev",
                skills=["Java"],
                provenance="ref2",
                allowed_uses=["cv"],
            ),
            CandidateFact(
                fact_id=f_to_remove,
                kind=EvidenceFactKind.SKILL,
                title="Obsolete Tool",
                provenance="ref3",
                allowed_uses=["cv"],
            ),
        ]
        snap_v1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=facts_v1,
        )

        # Snapshot v2: keep_unchanged (identical), to_edit (promoted to Senior, skill Python), to_add (new)
        facts_v2 = [
            CandidateFact(
                fact_id=f_keep_unchanged,
                kind=EvidenceFactKind.EDUCATION,
                title="B.Sc. CS",
                provenance="ref1",
                allowed_uses=["cv"],
            ),
            CandidateFact(
                fact_id=f_to_edit,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Senior Dev",  # edited
                skills=["Python"],  # edited
                provenance="ref2",
                allowed_uses=["cv"],
            ),
            CandidateFact(
                fact_id=f_to_add,
                kind=EvidenceFactKind.PROJECT,
                title="New Microservice",
                provenance="ref4",
                allowed_uses=["cv"],
            ),
        ]
        snap_v2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=facts_v2,
        )

        chunker = EvidenceChunker()
        m1, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v1, purpose="cv"))
        m2, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v2, purpose="cv"))
        assert m1 is not None and m2 is not None

        diff = compare_chunk_manifests(m1, m2)
        assert diff.replacement_required is True

        # Find chunk IDs
        chunk_map1 = {c.primary_fact_id: c.chunk_id for c in m1.chunks}
        chunk_map2 = {c.primary_fact_id: c.chunk_id for c in m2.chunks}

        # Added: f_to_add
        assert chunk_map2[f_to_add] in diff.added_chunk_ids
        # Removed: f_to_remove
        assert chunk_map1[f_to_remove] in diff.removed_chunk_ids
        # Updated: f_to_edit
        assert chunk_map2[f_to_edit] in diff.content_changed_chunk_ids
        # Rebound unchanged: f_keep_unchanged
        assert chunk_map2[f_keep_unchanged] in diff.rebound_unchanged_chunk_ids

    def test_permission_narrowing_removes_chunk_from_target_manifest(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()

        # v1: permitted for cv
        fact_v1 = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.PROJECT,
            title="Side Project",
            provenance="ref",
            allowed_uses=["cv"],
        )
        # v2: permissions restricted to private
        fact_v2 = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.PROJECT,
            title="Side Project",
            provenance="ref",
            allowed_uses=[],  # private now
        )

        snap1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_v1],
        )
        snap2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_v2],
        )
        assert snap1 is not None

        chunker = EvidenceChunker()
        m1, _ = chunker.build(ChunkBuildRequest(snapshot=snap1, purpose="cv"))
        m2, _ = chunker.build(ChunkBuildRequest(snapshot=snap2, purpose="cv"))
        assert m1 is not None and m2 is not None

        diff = compare_chunk_manifests(m1, m2)
        # Fact removed from CV target manifest
        assert m1.chunks[0].chunk_id in diff.removed_chunk_ids
        assert len(m2.chunks) == 0

    def test_cross_candidate_and_cross_purpose_comparison_fails_validation(self) -> None:
        snap1 = ProfileSnapshot(
            candidate_id=uuid.uuid4(),
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[],
        )
        snap2 = ProfileSnapshot(
            candidate_id=uuid.uuid4(),  # Different candidate
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[],
        )

        chunker = EvidenceChunker()
        m1, _ = chunker.build(ChunkBuildRequest(snapshot=snap1, purpose="cv"))
        m2, _ = chunker.build(ChunkBuildRequest(snapshot=snap2, purpose="cv"))
        assert m1 is not None and m2 is not None

        with pytest.raises(ChunkValidationError) as exc_info:
            compare_chunk_manifests(m1, m2)
        assert "Cannot compare manifests across different candidates" in str(exc_info.value)
