"""Tests for stable identity, content versioning, and snapshot binding fingerprints (CONTEXT-02-S04)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_identity import (
    generate_chunk_id,
)
from job_automation.context.chunk_preparation import ChunkEvidencePreparer
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import ChunkingSettings
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from tests.context.chunk_test_helpers import make_approval


class TestChunkIdentity:
    def test_chunk_id_stability_across_fact_corrections_and_reparenting(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        purpose = "assessment"

        id1 = generate_chunk_id("v1", cid, purpose, fid)

        # Fact corrected with new claims, different title, new dates
        id2 = generate_chunk_id("v1", cid, purpose, fid)
        assert id1 == id2

        # Changing candidate_id -> new chunk_id
        id_other_cand = generate_chunk_id("v1", uuid.uuid4(), purpose, fid)
        assert id_other_cand != id1

        # Changing purpose -> new chunk_id
        id_cv = generate_chunk_id("v1", cid, "cv", fid)
        assert id_cv != id1

        # Changing fact_id -> new chunk_id
        id_other_fact = generate_chunk_id("v1", cid, purpose, uuid.uuid4())
        assert id_other_fact != id1

    def test_chunk_version_retains_identical_hash_for_unchanged_content_across_versions(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()

        fact_v1 = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Engineer",
            skills=["Python"],
            provenance="cert.pdf",
            allowed_uses=["cv"],
        )
        fact_v2 = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Engineer",
            skills=["Python"],
            provenance="cert.pdf",
            allowed_uses=["cv"],
        )

        snap1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_v1],
        )
        snap2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_v2],
        )

        preparer = ChunkEvidencePreparer()
        prep1 = preparer.prepare(snap1, purpose="cv", settings=ChunkingSettings())
        prep2 = preparer.prepare(snap2, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        chunk1 = builder.build_chunk(cid, "v1", "cv", prep1.prepared_facts[0], ChunkingSettings())
        chunk2 = builder.build_chunk(cid, "v2", "cv", prep2.prepared_facts[0], ChunkingSettings())

        # Same chunk_id
        assert chunk1.chunk_id == chunk2.chunk_id
        # Content version is IDENTICAL because content did not change
        assert chunk1.chunk_version == chunk2.chunk_version
        # But binding fingerprint is DIFFERENT because profile_version cited is v1 vs v2
        assert chunk1.binding_fingerprint != chunk2.binding_fingerprint
        assert chunk1.profile_version == "v1"
        assert chunk2.profile_version == "v2"

    def test_fact_text_change_alters_chunk_version(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()

        fact_orig = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Software Developer",
            skills=["Python"],
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )
        fact_edited = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Software Developer",  # edited title
            skills=["Python"],
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )

        snap1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_orig],
        )
        snap2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[fact_edited],
        )

        preparer = ChunkEvidencePreparer()
        prep1 = preparer.prepare(snap1, purpose="cv", settings=ChunkingSettings())
        prep2 = preparer.prepare(snap2, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        chunk1 = builder.build_chunk(cid, "v1", "cv", prep1.prepared_facts[0], ChunkingSettings())
        chunk2 = builder.build_chunk(cid, "v2", "cv", prep2.prepared_facts[0], ChunkingSettings())

        # chunk_id is retained
        assert chunk1.chunk_id == chunk2.chunk_id
        # chunk_version is CHANGED
        assert chunk1.chunk_version != chunk2.chunk_version

    def test_ancestor_change_invalidates_descendant_chunk_version(self) -> None:
        cid = uuid.uuid4()
        f_parent = uuid.uuid4()
        f_child = uuid.uuid4()

        # v1: parent has title "Lead Dev"
        p_v1 = CandidateFact(
            fact_id=f_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Lead Dev",
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )
        c_v1 = CandidateFact(
            fact_id=f_child,
            parent_id=f_parent,
            kind=EvidenceFactKind.PROJECT,
            title="API Gateway",
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )

        # v2: parent title corrected to "Principal Architect" (child unchanged)
        p_v2 = CandidateFact(
            fact_id=f_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Principal Architect",
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )
        c_v2 = CandidateFact(
            fact_id=f_child,
            parent_id=f_parent,
            kind=EvidenceFactKind.PROJECT,
            title="API Gateway",
            provenance="ref.pdf",
            allowed_uses=["cv"],
        )

        snap1 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[p_v1, c_v1],
        )
        snap2 = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v2",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[p_v2, c_v2],
        )

        preparer = ChunkEvidencePreparer()
        prep1 = preparer.prepare(snap1, purpose="cv", settings=ChunkingSettings())
        prep2 = preparer.prepare(snap2, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        child_prep1 = [pf for pf in prep1.prepared_facts if pf.primary_fact.fact_id == f_child][0]
        child_prep2 = [pf for pf in prep2.prepared_facts if pf.primary_fact.fact_id == f_child][0]

        child_chunk1 = builder.build_chunk(cid, "v1", "cv", child_prep1, ChunkingSettings())
        child_chunk2 = builder.build_chunk(cid, "v2", "cv", child_prep2, ChunkingSettings())

        # Same chunk_id
        assert child_chunk1.chunk_id == child_chunk2.chunk_id
        # Content version changed because ancestor dependency changed
        assert child_chunk1.chunk_version != child_chunk2.chunk_version
