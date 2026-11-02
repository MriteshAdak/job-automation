"""Tests for parent context retention, non-role parents, and privacy boundaries (CONTEXT-02-S03)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_builder import ChunkBuilder
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


class TestChunkParentContext:
    def test_permitted_ancestors_rendered_separately(self) -> None:
        cid = uuid.uuid4()
        f_emp = uuid.uuid4()
        f_proj = uuid.uuid4()

        emp_fact = CandidateFact(
            fact_id=f_emp,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Principal Engineer",
            organization="Siemens AG",
            start_date=PrecisionDate(value="2018-05", precision="month"),
            end_date=PrecisionDate(value="2022-09", precision="month"),
            provenance="emp_cert.pdf",
            allowed_uses=["cv", "assessment"],
        )
        proj_fact = CandidateFact(
            fact_id=f_proj,
            parent_id=f_emp,
            kind=EvidenceFactKind.PROJECT,
            title="Industrial IoT Gateway",
            skills=["C++", "MQTT"],
            claims=["Designed real-time telemetry protocol"],
            provenance="proj_rep.pdf",
            allowed_uses=["cv", "assessment"],
        )

        snap = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[emp_fact, proj_fact],
        )

        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())

        builder = ChunkBuilder()
        proj_prep = [pf for pf in prep_data.prepared_facts if pf.primary_fact.fact_id == f_proj][0]
        chunk = builder.build_chunk(cid, "v1", "cv", proj_prep, ChunkingSettings())

        assert len(chunk.ancestor_context) == 1
        assert chunk.ancestor_context[0].title == "Principal Engineer"
        assert chunk.ancestor_context[0].organization == "Siemens AG"
        assert "[Parent Context]" in chunk.retrieval_text
        assert "Kind: employment" in chunk.retrieval_text
        assert "Principal Engineer" in chunk.retrieval_text
        assert "Siemens AG" in chunk.retrieval_text
        assert "[Evidence]" in chunk.retrieval_text
        assert "Industrial IoT Gateway" in chunk.retrieval_text

    def test_sentinel_secret_in_private_parent_never_leaks_to_child_chunk(self) -> None:
        cid = uuid.uuid4()
        f_secret_parent = uuid.uuid4()
        f_public_child = uuid.uuid4()

        secret_sentinel = "TOP_SECRET_DEFENSE_SATELLITE_KEY_998877"

        parent_fact = CandidateFact(
            fact_id=f_secret_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title=f"Secret Operative: {secret_sentinel}",
            organization="BlackOps Security Systems",
            claims=[f"Built confidential payload {secret_sentinel}"],
            provenance="classified.pdf",
            allowed_uses=[],  # Forbidden everywhere
        )
        child_fact = CandidateFact(
            fact_id=f_public_child,
            parent_id=f_secret_parent,
            kind=EvidenceFactKind.PROJECT,
            title="Public Networking Stack",
            claims=["Implemented open RFC-compliant socket library"],
            skills=["Networking", "Rust"],
            provenance="github.com/public",
            allowed_uses=["cv", "assessment", "cover_letter"],
        )

        snap = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[parent_fact, child_fact],
        )

        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings(strict_parents=False))

        child_prep = [pf for pf in prep_data.prepared_facts if pf.primary_fact.fact_id == f_public_child][0]
        builder = ChunkBuilder()
        chunk = builder.build_chunk(cid, "v1", "cv", child_prep, ChunkingSettings())

        # Assert sentinel secret is nowhere in chunk retrieval_text
        assert secret_sentinel not in chunk.retrieval_text
        assert "BlackOps Security Systems" not in chunk.retrieval_text

        # Assert sentinel secret is nowhere in sources
        for sm in chunk.sources:
            assert secret_sentinel not in (sm.exact_value or "")

        # Child retains opaque parent_id and limitation
        assert chunk.parent_id == f_secret_parent
        assert any(f"restricted_parent_omitted:{f_secret_parent}" in lim for lim in chunk.contextual_limitations)

    def test_non_role_parent_chain(self) -> None:
        cid = uuid.uuid4()
        f_edu = uuid.uuid4()
        f_thesis = uuid.uuid4()

        edu_fact = CandidateFact(
            fact_id=f_edu,
            kind=EvidenceFactKind.EDUCATION,
            title="M.Sc. Computer Science",
            organization="RWTH Aachen",
            start_date=PrecisionDate(value="2018", precision="year"),
            end_date=PrecisionDate(value="2020", precision="year"),
            provenance="master_cert.pdf",
            allowed_uses=["cv"],
        )
        thesis_fact = CandidateFact(
            fact_id=f_thesis,
            parent_id=f_edu,
            kind=EvidenceFactKind.PUBLICATION,
            title="Distributed Consensus via Raft",
            claims=["Published in IEEE Proceedings"],
            provenance="ieee_link",
            allowed_uses=["cv"],
        )

        snap = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[edu_fact, thesis_fact],
        )

        preparer = ChunkEvidencePreparer()
        prep_data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())

        thesis_prep = [pf for pf in prep_data.prepared_facts if pf.primary_fact.fact_id == f_thesis][0]
        builder = ChunkBuilder()
        chunk = builder.build_chunk(cid, "v1", "cv", thesis_prep, ChunkingSettings())

        assert len(chunk.ancestor_context) == 1
        assert chunk.ancestor_context[0].kind == EvidenceFactKind.EDUCATION
        assert chunk.ancestor_context[0].title == "M.Sc. Computer Science"
        assert "Kind: education" in chunk.retrieval_text
