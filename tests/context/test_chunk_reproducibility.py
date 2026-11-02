"""Tests for byte-for-byte reproducibility and input order independence (CONTEXT-02-S04)."""

from __future__ import annotations

import random
import uuid

import pytest

from job_automation.context.chunk_serialization import serialize_chunk_set_to_json
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import ChunkBuildRequest, ChunkingSettings
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


def create_multi_fact_snapshot() -> ProfileSnapshot:
    cid = uuid.uuid4()
    facts = [
        CandidateFact(
            fact_id=uuid.uuid4(),
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Architect",
            organization="Alpha GmbH",
            start_date=PrecisionDate(value="2022-01", precision="month"),
            skills=["Python", "FastAPI"],
            provenance="cert1.pdf",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=uuid.uuid4(),
            kind=EvidenceFactKind.EDUCATION,
            title="M.Sc. Computer Science",
            organization="TU Berlin",
            start_date=PrecisionDate(value="2018", precision="year"),
            provenance="cert2.pdf",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=uuid.uuid4(),
            kind=EvidenceFactKind.PROJECT,
            title="Data Lake Ingestion",
            start_date=PrecisionDate(value="2020-06", precision="month"),
            skills=["AWS", "PySpark"],
            provenance="report.pdf",
            allowed_uses=["assessment", "cv"],
        ),
    ]

    return ProfileSnapshot(
        candidate_id=cid,
        profile_version="v1",
        approval_metadata=make_approval(approved_by="tester@example.com"),
        explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
        evidence_records=facts,
    )


class TestChunkReproducibility:
    def test_repeated_builds_are_byte_identical(self) -> None:
        snap = create_multi_fact_snapshot()
        chunker = EvidenceChunker()
        req = ChunkBuildRequest(snapshot=snap, purpose="cv", settings=ChunkingSettings())

        manifest1, err1 = chunker.build(req)
        assert err1 is None
        assert manifest1 is not None

        manifest2, err2 = chunker.build(req)
        assert err2 is None
        assert manifest2 is not None

        # Identical manifest fingerprint
        assert manifest1.manifest_fingerprint == manifest2.manifest_fingerprint

        # Identical canonical serialized bytes
        bytes1 = serialize_chunk_set_to_json(manifest1)
        bytes2 = serialize_chunk_set_to_json(manifest2)
        assert bytes1 == bytes2

    def test_input_fact_reordering_does_not_change_manifest_or_order(self) -> None:
        snap = create_multi_fact_snapshot()
        chunker = EvidenceChunker()

        req1 = ChunkBuildRequest(snapshot=snap, purpose="assessment")
        manifest1, err1 = chunker.build(req1)
        assert err1 is None
        assert manifest1 is not None

        # Create copy of snapshot with reversed and shuffled evidence records
        shuffled_records = list(snap.evidence_records)
        random.seed(42)
        random.shuffle(shuffled_records)

        shuffled_snap = ProfileSnapshot(
            candidate_id=snap.candidate_id,
            profile_version=snap.profile_version,
            approval_metadata=snap.approval_metadata,
            explicit_eligibility=snap.explicit_eligibility,
            evidence_records=shuffled_records,
        )

        req2 = ChunkBuildRequest(snapshot=shuffled_snap, purpose="assessment")
        manifest2, err2 = chunker.build(req2)
        assert err2 is None
        assert manifest2 is not None

        # Manifest fingerprints match exactly
        assert manifest1.manifest_fingerprint == manifest2.manifest_fingerprint

        # Output chunk order matches exactly
        assert [c.chunk_id for c in manifest1.chunks] == [c.chunk_id for c in manifest2.chunks]
        assert [c.primary_fact_id for c in manifest1.chunks] == [c.primary_fact_id for c in manifest2.chunks]
