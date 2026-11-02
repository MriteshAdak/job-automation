"""Tests for ProfileRepository persistence, immutability, rollback, and detached reads."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.models import (
    DraftFact,
    DraftProfile,
    ProvenanceRecord,
)
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError


class TestProfileRepository:
    def test_draft_lifecycle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "draft_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            candidate_id = uuid.uuid4()
            fact_id = uuid.uuid4()
            now = datetime.now(timezone.utc)

            draft = DraftProfile(
                candidate_id=candidate_id,
                proposed_eligibility=CandidateEligibility(work_authorization_countries=["DE"]),
                facts=[
                    DraftFact(
                        fact_id=fact_id,
                        kind=EvidenceFactKind.EMPLOYMENT,
                        title="Backend Dev",
                        claims=["Built microservices"],
                        skills=["Python"],
                    )
                ],
                notes="Initial draft proposal",
                created_at=now,
                updated_at=now,
            )

            # Save draft
            repo.save_draft(draft)

            # Retrieve draft
            loaded = repo.get_draft(draft.draft_id)
            assert loaded is not None
            assert loaded.draft_id == draft.draft_id
            assert loaded.candidate_id == candidate_id
            assert len(loaded.facts) == 1
            assert loaded.facts[0].title == "Backend Dev"
            assert loaded.content_digest == draft.content_digest

            # List drafts
            drafts = repo.list_drafts(candidate_id)
            assert len(drafts) == 1

            # Delete draft
            assert repo.delete_draft(draft.draft_id) is True
            assert repo.get_draft(draft.draft_id) is None

    def test_provenance_lifecycle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "prov_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            cid = uuid.uuid4()
            now = datetime.now(timezone.utc)
            rec = ProvenanceRecord(
                provenance_id="doc_001",
                candidate_id=cid,
                source_type="document",
                locator="Section 3, p. 12",
                content_hash="sha256:abcd1234",
                file_path="cid/doc.pdf",
                captured_at=now,
                notes="Verified certificate",
            )
            repo.save_provenance(rec)

            loaded = repo.get_provenance("doc_001")
            assert loaded is not None
            assert loaded.locator == "Section 3, p. 12"
            assert loaded.content_hash == "sha256:abcd1234"

            all_prov = repo.list_provenance(cid)
            assert len(all_prov) == 1

    def test_snapshot_immutability_and_idempotency(self, tmp_path: Path) -> None:
        db_path = tmp_path / "snap_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            cid = uuid.uuid4()
            fid = uuid.uuid4()
            now = datetime.now(timezone.utc)

            fact = CandidateFact(
                fact_id=fid,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Lead Architect",
                provenance="contract.pdf",
                allowed_uses=["cv", "assessment"],
            )
            snap = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v1",
                approval_metadata=ProfileApprovalMetadata(
                    is_approved=True,
                    approved_by="candidate",
                    approved_at=now,
                ),
                explicit_eligibility=CandidateEligibility(remote_eligible=True),
                evidence_records=[fact],
            )

            # First publication
            repo.publish_snapshot(
                snapshot=snap,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:hash_v1",
                approved_by="candidate",
                approved_at=now,
                notes="Initial approved release",
                is_current=True,
            )

            # Verify current pointer
            assert repo.get_current_version(cid) == "v1"
            current_snap = repo.get_current_snapshot(cid)
            assert current_snap is not None
            assert current_snap.profile_version == "v1"
            assert len(current_snap.evidence_records) == 1

            # Idempotent re-publication with identical content_hash succeeds
            repo.publish_snapshot(
                snapshot=snap,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:hash_v1",
                approved_by="candidate",
                approved_at=now,
                notes="Initial approved release",
                is_current=True,
            )

            # Re-publishing under SAME version with DIFFERENT content hash raises DuplicateKeyError
            with pytest.raises(DuplicateKeyError, match="already published with different content hash"):
                repo.publish_snapshot(
                    snapshot=snap,
                    version_sequence=1,
                    predecessor_version=None,
                    content_hash="sha256:altered_content_hash",
                    approved_by="candidate",
                    approved_at=now,
                )

    def test_publication_rollback_on_transaction_failure(self, tmp_path: Path) -> None:
        db_path = tmp_path / "rollback_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            cid = uuid.uuid4()
            now = datetime.now(timezone.utc)
            snap = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v1",
                approval_metadata=ProfileApprovalMetadata(
                    is_approved=True,
                    approved_by="candidate",
                    approved_at=now,
                ),
                explicit_eligibility=CandidateEligibility(),
                evidence_records=[],
            )

            with pytest.raises(RuntimeError, match="Simulated crash"):
                with engine.transaction():
                    repo.publish_snapshot(
                        snapshot=snap,
                        version_sequence=1,
                        predecessor_version=None,
                        content_hash="sha256:hash_v1",
                        approved_by="candidate",
                        approved_at=now,
                        is_current=True,
                    )
                    raise RuntimeError("Simulated crash mid-transaction")

            # Check nothing was committed
            assert repo.get_snapshot("v1") is None
            assert repo.get_current_version(cid) is None
            assert len(repo.get_version_history(cid)) == 0

    def test_detached_reads_isolation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "detached_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.migrate()
            repo = engine.profiles

            cid = uuid.uuid4()
            fid = uuid.uuid4()
            now = datetime.now(timezone.utc)
            fact = CandidateFact(
                fact_id=fid,
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Original Title",
                claims=["Original claim"],
                provenance="test",
            )
            snap = ProfileSnapshot(
                candidate_id=cid,
                profile_version="v1",
                approval_metadata=ProfileApprovalMetadata(
                    is_approved=True,
                    approved_by="candidate",
                    approved_at=now,
                ),
                explicit_eligibility=CandidateEligibility(),
                evidence_records=[fact],
            )
            repo.publish_snapshot(
                snapshot=snap,
                version_sequence=1,
                predecessor_version=None,
                content_hash="sha256:hash",
                approved_by="candidate",
                approved_at=now,
            )

            # Read snapshot and mutate the list
            read1 = repo.get_snapshot("v1")
            assert read1 is not None
            # Mutate local object
            read1.evidence_records.clear()
            assert len(read1.evidence_records) == 0

            # Second read should still have the original record intact
            read2 = repo.get_snapshot("v1")
            assert read2 is not None
            assert len(read2.evidence_records) == 1
            assert read2.evidence_records[0].title == "Original Title"
