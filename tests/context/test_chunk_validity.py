"""Tests for consumer binding validation against expected target context (CONTEXT-02-S05)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_service import EvidenceChunker
from job_automation.context.chunk_validity import validate_chunk_binding
from job_automation.contracts.evidence_chunks import ChunkBuildRequest, ChunkingSettings
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


def create_empty_snapshot(cid: uuid.UUID, pv: str) -> ProfileSnapshot:
    return ProfileSnapshot(
        candidate_id=cid,
        profile_version=pv,
        approval_metadata=make_approval(approved_by="tester"),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=[],
    )


class TestChunkValidity:
    def test_valid_binding_passes(self) -> None:
        cid = uuid.uuid4()
        snap = create_empty_snapshot(cid, "v1")
        chunker = EvidenceChunker()
        manifest, err = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="assessment"))
        assert err is None
        assert manifest is not None

        valid, msg = validate_chunk_binding(
            chunk_set=manifest,
            expected_candidate_id=cid,
            expected_profile_version="v1",
            expected_purpose="assessment",
            expected_settings_fingerprint=manifest.settings_fingerprint,
        )
        assert valid is True
        assert msg is None

    def test_candidate_mismatch_fails(self) -> None:
        cid = uuid.uuid4()
        other_cid = uuid.uuid4()
        snap = create_empty_snapshot(cid, "v1")
        chunker = EvidenceChunker()
        manifest, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="assessment"))
        assert manifest is not None

        valid, msg = validate_chunk_binding(
            chunk_set=manifest,
            expected_candidate_id=other_cid,
            expected_profile_version="v1",
            expected_purpose="assessment",
        )
        assert valid is False
        assert "Candidate mismatch" in (msg or "")

    def test_profile_version_mismatch_fails(self) -> None:
        cid = uuid.uuid4()
        snap = create_empty_snapshot(cid, "v1")
        chunker = EvidenceChunker()
        manifest, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert manifest is not None

        valid, msg = validate_chunk_binding(
            chunk_set=manifest,
            expected_candidate_id=cid,
            expected_profile_version="v2",  # expected v2, got v1
            expected_purpose="cv",
        )
        assert valid is False
        assert "Profile version mismatch" in (msg or "")

    def test_purpose_mismatch_fails(self) -> None:
        cid = uuid.uuid4()
        snap = create_empty_snapshot(cid, "v1")
        chunker = EvidenceChunker()
        manifest, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert manifest is not None

        valid, msg = validate_chunk_binding(
            chunk_set=manifest,
            expected_candidate_id=cid,
            expected_profile_version="v1",
            expected_purpose="cover_letter",  # expected cover_letter, got cv
        )
        assert valid is False
        assert "Purpose mismatch" in (msg or "")

    def test_settings_fingerprint_mismatch_fails(self) -> None:
        cid = uuid.uuid4()
        snap = create_empty_snapshot(cid, "v1")
        chunker = EvidenceChunker()
        manifest, _ = chunker.build(ChunkBuildRequest(snapshot=snap, purpose="cv"))
        assert manifest is not None

        valid, msg = validate_chunk_binding(
            chunk_set=manifest,
            expected_candidate_id=cid,
            expected_profile_version="v1",
            expected_purpose="cv",
            expected_settings_fingerprint="different_settings_fingerprint",
        )
        assert valid is False
        assert "Settings fingerprint mismatch" in (msg or "")
