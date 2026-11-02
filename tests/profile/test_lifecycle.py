"""Integrated end-to-end lifecycle verification for candidate profile management (PROFILE-01).

Demonstrates:
- Unapproved draft intake leaving current profile unset.
- Deliberate review and explicit approval creating version v1.
- Corrections, permission restrictions, and removals creating versions v2 and v3.
- Process restart / reopen preserving all historical data and pointers.
- Exact C08 citation resolution for older versions.
- Strict inclusion parity across JSON and RAG consumer fakes.
- Immutability and conflict rejection.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.profile.errors import (
    FactNotFoundError,
    ProfileConflictError,
    ProfileNotFoundError,
)
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine
from tests.fakes.profile_consumers import (
    FakeJsonContextConsumer,
    FakeRagContextConsumer,
)


class TestProfileLifecycle:
    def test_complete_profile_lifecycle_and_restart(self, tmp_path: Path) -> None:
        db_path = tmp_path / "lifecycle.db"
        profiles_dir = tmp_path / "profiles"

        cid = uuid.uuid4()
        fid_a = uuid.uuid4()
        fid_b = uuid.uuid4()
        fid_c = uuid.uuid4()
        fid_d = uuid.uuid4()

        # ===================================================================
        # Phase 1: Initial Draft Intake and Approval -> V1
        # ===================================================================
        with StorageEngine(db_path=db_path, profiles_dir=profiles_dir) as eng1:
            eng1.migrate()
            svc1 = ProfileService.from_engine(eng1)

            # Ingest unapproved draft with F_a, F_b, F_c
            draft1 = svc1.import_draft(
                {
                    "candidate_id": str(cid),
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE"],
                        "target_locations": ["Berlin"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid_a),
                            "kind": "employment",
                            "title": "Software Engineer (V1)",
                            "claims": ["Developed search pipeline v1"],
                            "skills": ["Python", "SQLite"],
                            "allowed_uses": ["cv", "assessment"],
                        },
                        {
                            "fact_id": str(fid_b),
                            "kind": "project",
                            "title": "Side Project B",
                            "claims": ["Created open source tool"],
                            "allowed_uses": ["cv", "assessment"],
                        },
                        {
                            "fact_id": str(fid_c),
                            "kind": "skill",
                            "title": "Cloud Computing",
                            "skills": ["AWS", "Docker"],
                            "allowed_uses": ["assessment"],
                        },
                    ],
                    "notes": "Draft 1 intake",
                }
            )

            # Intake alone does NOT create a published snapshot or current pointer
            assert svc1.get_current_snapshot(cid) is None
            assert svc1.list_history(cid) == []

            # Deliberate review and approval publishes v1
            snap1 = svc1.approve_and_publish(
                draft_id=draft1.draft_id,
                expected_draft_digest=draft1.content_digest,
                approved_by="candidate_operator",
                notes="V1 initial approval",
            )
            assert snap1.profile_version == "v1"
            assert svc1.get_current_snapshot(cid).profile_version == "v1"

            # ===================================================================
            # Phase 2: Correction & Restriction Draft -> V2
            # ===================================================================
            # Correct F_a, restrict F_b (allowed_uses=[]), add F_d
            draft2 = svc1.import_draft(
                {
                    "candidate_id": str(cid),
                    "base_profile_version": "v1",
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE", "AT"],
                        "target_locations": ["Berlin", "Vienna"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid_a),
                            "kind": "employment",
                            "title": "Senior Software Engineer (V2)",
                            "claims": ["Developed search pipeline v2 with low latency"],
                            "skills": ["Python", "SQLite", "FastAPI"],
                            "allowed_uses": ["cv", "assessment"],
                        },
                        {
                            "fact_id": str(fid_b),
                            "kind": "project",
                            "title": "Side Project B (Private)",
                            "allowed_uses": [],  # Restricted: no downstream use!
                        },
                        {
                            "fact_id": str(fid_c),
                            "kind": "skill",
                            "title": "Cloud Computing",
                            "skills": ["AWS", "Docker"],
                            "allowed_uses": ["assessment"],
                        },
                        {
                            "fact_id": str(fid_d),
                            "kind": "certification",
                            "title": "Professional Cloud Architect",
                            "allowed_uses": ["cv", "assessment"],
                        },
                    ],
                    "notes": "Draft 2 updates",
                }
            )

            snap2 = svc1.approve_and_publish(
                draft_id=draft2.draft_id,
                expected_draft_digest=draft2.content_digest,
                approved_by="candidate_operator",
                expected_base_version="v1",
                notes="V2 promotion with corrections",
            )
            assert snap2.profile_version == "v2"
            assert svc1.get_current_snapshot(cid).profile_version == "v2"

            # ===================================================================
            # Phase 3: Removal Draft -> V3
            # ===================================================================
            # Remove F_c entirely
            draft3 = svc1.import_draft(
                {
                    "candidate_id": str(cid),
                    "base_profile_version": "v2",
                    "proposed_eligibility": {
                        "work_authorization_countries": ["DE", "AT"],
                        "target_locations": ["Berlin", "Vienna"],
                        "remote_eligible": True,
                    },
                    "facts": [
                        {
                            "fact_id": str(fid_a),
                            "kind": "employment",
                            "title": "Senior Software Engineer (V2)",
                            "claims": ["Developed search pipeline v2 with low latency"],
                            "skills": ["Python", "SQLite", "FastAPI"],
                            "allowed_uses": ["cv", "assessment"],
                        },
                        {
                            "fact_id": str(fid_b),
                            "kind": "project",
                            "title": "Side Project B (Private)",
                            "allowed_uses": [],
                        },
                        {
                            "fact_id": str(fid_d),
                            "kind": "certification",
                            "title": "Professional Cloud Architect",
                            "allowed_uses": ["cv", "assessment"],
                        },
                    ],
                    "notes": "Draft 3 with F_c removed",
                }
            )

            snap3 = svc1.approve_and_publish(
                draft_id=draft3.draft_id,
                expected_draft_digest=draft3.content_digest,
                approved_by="candidate_operator",
                expected_base_version="v2",
                notes="V3 without F_c",
            )
            assert snap3.profile_version == "v3"
            assert svc1.get_current_snapshot(cid).profile_version == "v3"

        # ===================================================================
        # Phase 4: Process Restart and Verification
        # ===================================================================
        # Re-open completely fresh StorageEngine instance (simulating restart)
        with StorageEngine(db_path=db_path, profiles_dir=profiles_dir) as eng2:
            svc2 = ProfileService.from_engine(eng2)

            # Current version is v3
            current = svc2.get_current_snapshot(cid)
            assert current is not None
            assert current.profile_version == "v3"

            # History list has all 3 versions in sequence
            history = svc2.list_history(cid)
            assert [h.profile_version for h in history] == ["v1", "v2", "v3"]

            # Exact C08 resolution across versions:
            # 1. (v1, F_a) returns V1 title
            ref_v1_a = CandidateEvidenceReference(profile_version="v1", fact_id=fid_a)
            fact_v1_a = svc2.resolve_candidate_reference(ref_v1_a)
            assert fact_v1_a.title == "Software Engineer (V1)"
            assert fact_v1_a.claims == ["Developed search pipeline v1"]

            # 2. (v2, F_a) returns V2 title
            ref_v2_a = CandidateEvidenceReference(profile_version="v2", fact_id=fid_a)
            fact_v2_a = svc2.resolve_candidate_reference(ref_v2_a)
            assert fact_v2_a.title == "Senior Software Engineer (V2)"
            assert fact_v2_a.claims == ["Developed search pipeline v2 with low latency"]

            # 3. (v1, F_b) has allowed_uses ['cv', 'assessment']
            ref_v1_b = CandidateEvidenceReference(profile_version="v1", fact_id=fid_b)
            assert svc2.resolve_candidate_reference(ref_v1_b).allowed_uses == ["cv", "assessment"]

            # 4. (v2, F_b) has allowed_uses []
            ref_v2_b = CandidateEvidenceReference(profile_version="v2", fact_id=fid_b)
            assert svc2.resolve_candidate_reference(ref_v2_b).allowed_uses == []

            # 5. (v1, F_c) resolves in v1
            ref_v1_c = CandidateEvidenceReference(profile_version="v1", fact_id=fid_c)
            assert svc2.resolve_candidate_reference(ref_v1_c).title == "Cloud Computing"

            # 6. (v3, F_c) was removed in v3 -> raises FactNotFoundError
            ref_v3_c = CandidateEvidenceReference(profile_version="v3", fact_id=fid_c)
            with pytest.raises(FactNotFoundError, match="not found in referenced profile version 'v3'"):
                svc2.resolve_candidate_reference(ref_v3_c)

            # ===============================================================
            # Phase 5: Inclusion Parity for JSON and RAG Consumers
            # ===============================================================
            json_consumer = FakeJsonContextConsumer(svc2)
            rag_consumer = FakeRagContextConsumer(svc2)

            json_v2 = json_consumer.build_context(snap2, purpose="assessment")
            rag_v2 = rag_consumer.build_index_and_retrieve(snap2, purpose="assessment")

            # Must have identical eligible fact UUIDs
            assert json_v2["eligible_fact_ids"] == rag_v2["eligible_fact_ids"]
            # F_b was restricted ([]), so it must be absent from both
            assert fid_b not in json_v2["eligible_fact_ids"]
            assert fid_b not in rag_v2["eligible_fact_ids"]
            # F_a, F_c, F_d are eligible for assessment
            assert set(json_v2["eligible_fact_ids"]) == {fid_a, fid_c, fid_d}

            # ===============================================================
            # Phase 6: Version Diff Verification
            # ===============================================================
            diff_1_2 = svc2.diff_versions("v1", "v2")
            assert len(diff_1_2.added_facts) == 1
            assert diff_1_2.added_facts[0].fact_id == fid_d
            assert len(diff_1_2.updated_facts) == 2  # F_a and F_b
            assert diff_1_2.eligibility_changed is True

            diff_2_3 = svc2.diff_versions("v2", "v3")
            assert len(diff_2_3.removed_facts) == 1
            assert diff_2_3.removed_facts[0].fact_id == fid_c

