"""Tests for downstream index consumer boundaries using FakeIndexConsumer (CONTEXT-02-S06)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_service import EvidenceChunker
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import ChunkBuildRequest
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval
from tests.fakes.chunk_consumer import FakeIndexConsumer


class TestChunkConsumerBoundary:
    def test_consumer_initial_ingest_and_change_set_application(self) -> None:
        cid = uuid.uuid4()
        fid_a = uuid.uuid4()
        fid_b = uuid.uuid4()
        fid_c = uuid.uuid4()

        # Snapshot v1: fid_a, fid_b
        snap_v1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=fid_a,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Backend Dev",
                    provenance="ref1",
                    allowed_uses=["cv"],
                ),
                CandidateFact(
                    fact_id=fid_b,
                    kind=EvidenceFactKind.SKILL,
                    title="Python",
                    provenance="ref2",
                    allowed_uses=["cv"],
                ),
            ],
        )

        chunker = EvidenceChunker()
        m1, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v1, purpose="cv"))
        assert m1 is not None

        consumer = FakeIndexConsumer()
        consumer.ingest_initial(m1)

        assert len(consumer.list_chunk_ids()) == 2
        assert consumer.verify_active_binding(cid, "v1", "cv") is True

        m1_map = {c.primary_fact_id: c.chunk_id for c in m1.chunks}
        chunk_a_id = m1_map[fid_a]
        chunk_b_id = m1_map[fid_b]

        # Snapshot v2: fid_a edited, fid_b removed, fid_c added
        snap_v2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=fid_a,
                    kind=EvidenceFactKind.EMPLOYMENT,
                    title="Senior Backend Dev",  # edited
                    provenance="ref1",
                    allowed_uses=["cv"],
                ),
                CandidateFact(
                    fact_id=fid_c,
                    kind=EvidenceFactKind.PROJECT,
                    title="Search Engine",
                    provenance="ref3",
                    allowed_uses=["cv"],
                ),
            ],
        )

        m2, _ = chunker.build(ChunkBuildRequest(snapshot=snap_v2, purpose="cv"))
        assert m2 is not None

        diff, _ = chunker.diff(m1, m2)
        assert diff is not None

        # Apply change set to consumer
        consumer.apply_change_set(diff, m2)

        # fid_b removed (in tombstones, absent from active chunks)
        assert chunk_b_id in consumer.tombstones
        assert consumer.get_chunk(chunk_b_id) is None

        # fid_a updated
        chunk_a_updated = consumer.get_chunk(chunk_a_id)
        assert chunk_a_updated is not None
        assert chunk_a_updated.title == "Senior Backend Dev"

        # Consumer active binding updated to v2
        assert consumer.verify_active_binding(cid, "v2", "cv") is True
        assert consumer.verify_active_binding(cid, "v1", "cv") is False
