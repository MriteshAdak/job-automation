"""Tests for evidence preparation, ancestor chains, and permission filtering (CONTEXT-02-S02)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.context.chunk_errors import (
    ChunkPermissionError,
    ChunkValidationError,
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


def create_hierarchical_snapshot() -> tuple[ProfileSnapshot, dict[str, uuid.UUID]]:
    cid = uuid.uuid4()
    f_role = uuid.uuid4()
    f_proj = uuid.uuid4()
    f_ach = uuid.uuid4()
    f_private_parent = uuid.uuid4()
    f_child_of_private = uuid.uuid4()
    f_cv_only = uuid.uuid4()
    f_empty_perm = uuid.uuid4()

    facts = [
        # Permitted 3-level hierarchy
        CandidateFact(
            fact_id=f_role,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Architect at Tech AG",
            organization="Tech AG",
            start_date=PrecisionDate(value="2020-01", precision="month"),
            end_date=PrecisionDate(value="2023-12", precision="month"),
            skills=["Python", "System Design"],
            claims=["Led platform architecture"],
            provenance="cert_2023.pdf",
            allowed_uses=["assessment", "cv", "cover_letter"],
        ),
        CandidateFact(
            fact_id=f_proj,
            parent_id=f_role,
            kind=EvidenceFactKind.PROJECT,
            title="Cloud Migration",
            start_date=PrecisionDate(value="2021", precision="year"),
            skills=["AWS", "Terraform"],
            claims=["Migrated legacy database"],
            provenance="report.pdf",
            allowed_uses=["assessment", "cv", "cover_letter"],
        ),
        CandidateFact(
            fact_id=f_ach,
            parent_id=f_proj,
            kind=EvidenceFactKind.AWARD,
            title="Zero Downtime Cutover",
            skills=["Docker"],
            claims=["Achieved 0 downtime"],
            provenance="log.txt",
            allowed_uses=["assessment", "cv"],
        ),
        # Hierarchy with private parent
        CandidateFact(
            fact_id=f_private_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Confidential Defense Project Role",
            organization="Defense Corp",
            start_date=PrecisionDate(value="2018", precision="year"),
            claims=["Secret government work"],
            provenance="nda.pdf",
            allowed_uses=[],  # Completely private
        ),
        CandidateFact(
            fact_id=f_child_of_private,
            parent_id=f_private_parent,
            kind=EvidenceFactKind.PROJECT,
            title="Public Open Source Module",
            start_date=PrecisionDate(value="2019", precision="year"),
            skills=["Rust"],
            claims=["Developed public crypto library"],
            provenance="github_crypto",
            allowed_uses=["assessment", "cv", "cover_letter"],
        ),
        # Purpose-specific fact
        CandidateFact(
            fact_id=f_cv_only,
            kind=EvidenceFactKind.CERTIFICATION,
            title="AWS Certified Solutions Architect",
            skills=["AWS"],
            provenance="cert_aws",
            allowed_uses=["cv"],
        ),
        # Empty permission fact
        CandidateFact(
            fact_id=f_empty_perm,
            kind=EvidenceFactKind.SKILL,
            title="Unused Skill Fact",
            provenance="unspecified",
            allowed_uses=[],
        ),
    ]

    snapshot = ProfileSnapshot(
        candidate_id=cid,
        profile_version="v1",
        approval_metadata=make_approval(
            approved_by="tester@example.com",
            notes="Hierarchical synthetic profile",
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE"],
            target_locations=["Berlin"],
            remote_eligible=True,
        ),
        evidence_records=facts,
    )

    ids = {
        "role": f_role,
        "proj": f_proj,
        "ach": f_ach,
        "private_parent": f_private_parent,
        "child_of_private": f_child_of_private,
        "cv_only": f_cv_only,
        "empty_perm": f_empty_perm,
    }
    return snapshot, ids


class TestChunkPreparation:
    def test_three_supported_purposes(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        settings = ChunkingSettings()

        for purpose in ["assessment", "cv", "cover_letter"]:
            data = preparer.prepare(snap, purpose=purpose, settings=settings)
            assert data.purpose == purpose
            assert len(data.eligible_fact_ids) > 0

    def test_unsupported_purpose_rejected(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        with pytest.raises(ChunkValidationError) as exc_info:
            preparer.prepare(snap, purpose="marketing_campaign", settings=ChunkingSettings())
        assert "Unsupported inclusion purpose" in str(exc_info.value)

    def test_empty_permissions_excluded_everywhere(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()

        for purpose in ["assessment", "cv", "cover_letter"]:
            data = preparer.prepare(snap, purpose=purpose, settings=ChunkingSettings())
            assert ids["empty_perm"] not in data.eligible_fact_ids
            assert ids["private_parent"] not in data.eligible_fact_ids

    def test_purpose_matrix_cv_only_fact(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()

        data_cv = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings())
        assert ids["cv_only"] in data_cv.eligible_fact_ids

        data_cov = preparer.prepare(snap, purpose="cover_letter", settings=ChunkingSettings())
        assert ids["cv_only"] not in data_cov.eligible_fact_ids

    def test_multi_level_permitted_ancestor_chain(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        data = preparer.prepare(snap, purpose="assessment", settings=ChunkingSettings())

        prep_map = {pf.primary_fact.fact_id: pf for pf in data.prepared_facts}

        # Check achievement (f_ach) has project and role as ancestors
        ach_prep = prep_map[ids["ach"]]
        assert len(ach_prep.ancestors) == 2
        # Ancestors ordered root to immediate parent: [role, proj]
        assert ach_prep.ancestors[0].fact_id == ids["role"]
        assert ach_prep.ancestors[0].kind == EvidenceFactKind.EMPLOYMENT
        assert ach_prep.ancestors[0].title == "Senior Architect at Tech AG"
        assert ach_prep.ancestors[1].fact_id == ids["proj"]
        assert ach_prep.ancestors[1].kind == EvidenceFactKind.PROJECT

        # Effective permissions: intersection of ach, proj, role
        # ach has ["assessment", "cv"], proj has ["assessment", "cv", "cover_letter"], role has ["assessment", "cv", "cover_letter"]
        # intersection is ["assessment", "cv"]
        assert ach_prep.effective_allowed_uses == ["assessment", "cv"]

    def test_optional_restricted_parent_retains_opaque_id_and_limitations(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        # Default settings: strict_parents=False
        data = preparer.prepare(snap, purpose="cv", settings=ChunkingSettings(strict_parents=False))

        prep_map = {pf.primary_fact.fact_id: pf for pf in data.prepared_facts}
        child_prep = prep_map[ids["child_of_private"]]

        # Child is eligible!
        assert child_prep.primary_fact.fact_id == ids["child_of_private"]
        # Retains opaque parent_id
        assert child_prep.primary_fact.parent_id == ids["private_parent"]
        # Ancestors list is empty because private parent text is omitted
        assert len(child_prep.ancestors) == 0
        # Contextual limitation is recorded
        assert any(f"restricted_parent_omitted:{ids['private_parent']}" in lim for lim in child_prep.contextual_limitations)
        # Warning is present
        assert any("restricted and omitted" in w for w in data.warnings)

    def test_strict_parent_policy_raises_permission_conflict(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        # With strict_parents=True, an unpermitted parent causes failure
        with pytest.raises(ChunkPermissionError) as exc_info:
            preparer.prepare(snap, purpose="cv", settings=ChunkingSettings(strict_parents=True))
        assert "restricted from purpose" in str(exc_info.value)

    def test_required_restricted_parent_raises_permission_conflict(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        # Caller explicitly requires the private parent
        with pytest.raises(ChunkPermissionError) as exc_info:
            preparer.prepare(
                snap,
                purpose="cv",
                settings=ChunkingSettings(strict_parents=False),
                explicit_required_fact_ids=[ids["private_parent"]],
            )
        assert "restricted from purpose" in str(exc_info.value)

    def test_missing_required_fact_id_raises_validation_error(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        missing_id = uuid.uuid4()
        with pytest.raises(ChunkValidationError) as exc_info:
            preparer.prepare(
                snap,
                purpose="cv",
                settings=ChunkingSettings(),
                explicit_required_fact_ids=[missing_id],
            )
        assert "not found in profile snapshot" in str(exc_info.value)

    def test_defensive_copying_mutation_isolation(self) -> None:
        snap, ids = create_hierarchical_snapshot()
        preparer = ChunkEvidencePreparer()
        data = preparer.prepare(snap, purpose="assessment", settings=ChunkingSettings())

        prep_map = {pf.primary_fact.fact_id: pf for pf in data.prepared_facts}
        role_prep = prep_map[ids["role"]]

        # Modifying original snapshot fact does not mutate prepared fact
        orig_fact = [f for f in snap.evidence_records if f.fact_id == ids["role"]][0]
        orig_fact.skills.append("MUTATED_SKILL")

        assert "MUTATED_SKILL" not in role_prep.primary_fact.skills

    def test_empty_eligible_evidence_produces_empty_prepared_data(self) -> None:
        cid = uuid.uuid4()
        private_only = ProfileSnapshot(
            candidate_id=cid,
            profile_version="v1",
            approval_metadata=make_approval(approved_by="tester@example.com"),
            explicit_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
            evidence_records=[
                CandidateFact(
                    fact_id=uuid.uuid4(),
                    kind=EvidenceFactKind.SKILL,
                    title="Hidden",
                    provenance="secret.pdf",
                    allowed_uses=[],
                )
            ],
        )
        preparer = ChunkEvidencePreparer()
        data = preparer.prepare(private_only, purpose="cv", settings=ChunkingSettings())
        assert len(data.prepared_facts) == 0
        assert len(data.eligible_fact_ids) == 0
        assert data.excluded_fact_count == 1
