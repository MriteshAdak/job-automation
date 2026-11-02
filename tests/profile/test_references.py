"""Tests for C08 candidate reference resolution against exact historical versions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence import (
    CandidateEvidenceReference,
    JobEvidenceReference,
)
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.errors import (
    FactNotFoundError,
    ProfileNotFoundError,
    ProfileValidationError,
)
from job_automation.profile.references import resolve_candidate_evidence_reference
from job_automation.storage.engine import StorageEngine


class TestProfileReferences:
    def test_exact_historical_c08_resolution(self, tmp_path: Path) -> None:
        db_path = tmp_path / "ref_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            cid = uuid.uuid4()
            fid_a = uuid.uuid4()
            now = datetime.now(timezone.utc)

            # v1 has fid_a with title "Title V1"
            fact_v1 = CandidateFact(
                fact_id=fid_a,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Title V1",
                claims=["Claim V1"],
                provenance="prov_v1",
            )
            snap_v1 = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v1",
                approval_metadata=ProfileApprovalMetadata(is_approved=True, approved_by="candidate", approved_at=now),
                explicit_eligibility=CandidateEligibility(),
                evidence_records=[fact_v1],
            )
            repo.publish_snapshot(
                snap_v1, version_sequence=1, predecessor_version=None, content_hash="sha256:v1", approved_by="c", approved_at=now
            )

            # v2 has fid_a updated with title "Title V2"
            fact_v2 = CandidateFact(
                fact_id=fid_a,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Title V2",
                claims=["Claim V2"],
                provenance="prov_v2",
            )
            snap_v2 = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v2",
                approval_metadata=ProfileApprovalMetadata(is_approved=True, approved_by="candidate", approved_at=now),
                explicit_eligibility=CandidateEligibility(),
                evidence_records=[fact_v2],
            )
            repo.publish_snapshot(
                snap_v2, version_sequence=2, predecessor_version="v1", content_hash="sha256:v2", approved_by="c", approved_at=now
            )

            # v3 omits fid_a
            snap_v3 = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v3",
                approval_metadata=ProfileApprovalMetadata(is_approved=True, approved_by="candidate", approved_at=now),
                explicit_eligibility=CandidateEligibility(),
                evidence_records=[],
            )
            repo.publish_snapshot(
                snap_v3, version_sequence=3, predecessor_version="v2", content_hash="sha256:v3", approved_by="c", approved_at=now
            )

            # 1. Resolve v1 citation: must return Title V1 exactly
            ref_v1 = CandidateEvidenceReference(profile_version="v1", fact_id=fid_a)
            res_v1 = resolve_candidate_evidence_reference(repo, ref_v1)
            assert res_v1.title == "Title V1"
            assert res_v1.provenance == "prov_v1"

            # 2. Resolve v2 citation: must return Title V2 exactly
            ref_v2 = CandidateEvidenceReference(profile_version="v2", fact_id=fid_a)
            res_v2 = resolve_candidate_evidence_reference(repo, ref_v2)
            assert res_v2.title == "Title V2"
            assert res_v2.provenance == "prov_v2"

            # 3. Resolve v3 citation: fid_a was omitted in v3 -> raises FactNotFoundError
            ref_v3 = CandidateEvidenceReference(profile_version="v3", fact_id=fid_a)
            with pytest.raises(FactNotFoundError, match="not found in referenced profile version 'v3'"):
                resolve_candidate_evidence_reference(repo, ref_v3)

            # 4. Unknown version -> raises ProfileNotFoundError
            ref_v99 = CandidateEvidenceReference(profile_version="v99", fact_id=fid_a)
            with pytest.raises(ProfileNotFoundError, match="does not exist"):
                resolve_candidate_evidence_reference(repo, ref_v99)

    def test_job_evidence_reference_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "job_ref_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            job_ref = JobEvidenceReference(
                posting_revision="rev-01",
                field_path="description",
                quotation="Requires Python",
            )
            with pytest.raises(ProfileValidationError, match="Cannot resolve job evidence reference"):
                resolve_candidate_evidence_reference(repo, job_ref)

