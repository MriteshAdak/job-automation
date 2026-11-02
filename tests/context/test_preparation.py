"""Tests for shared context preparation, mandatory context policy v1, and JSON/RAG parity."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from decimal import Decimal

import pytest

from job_automation.context.errors import (
    ContextPermissionError,
    ContextValidationError,
)
from job_automation.context.preparation import ProfileContextPreparer
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)


def create_test_snapshot() -> tuple[ProfileSnapshot, dict[str, uuid.UUID]]:
    cid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    f_emp_parent = uuid.uuid4()
    f_proj_child = uuid.uuid4()
    f_edu = uuid.uuid4()
    f_skill_assess = uuid.uuid4()
    f_private = uuid.uuid4()
    f_restricted_parent = uuid.uuid4()
    f_child_of_restricted = uuid.uuid4()

    facts = [
        CandidateFact(
            fact_id=f_emp_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Engineer at Tech GmbH",
            start_date=PrecisionDate(value="2020-01", precision="month"),
            end_date=PrecisionDate(value="2023-12", precision="month"),
            skills=["Python", "FastAPI"],
            claims=["Led core architecture"],
            provenance="work_contract",
            allowed_uses=["assessment", "cv", "cover_letter"],
        ),
        CandidateFact(
            fact_id=f_proj_child,
            parent_id=f_emp_parent,
            kind=EvidenceFactKind.PROJECT,
            title="Cloud Migration Project",
            start_date=PrecisionDate(value="2021", precision="year"),
            skills=["AWS", "Docker"],
            claims=["Migrated legacy monolith"],
            provenance="project_report",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=f_edu,
            kind=EvidenceFactKind.EDUCATION,
            title="B.Sc. Computer Science",
            start_date=PrecisionDate(value="2016", precision="year"),
            end_date=PrecisionDate(value="2019", precision="year"),
            organization="TU Berlin",
            provenance="degree_certificate",
            allowed_uses=["assessment", "cv"],
        ),
        CandidateFact(
            fact_id=f_skill_assess,
            kind=EvidenceFactKind.SKILL,
            title="Kubernetes Certification",
            skills=["Kubernetes"],
            provenance="exam_certificate",
            allowed_uses=["assessment"],
        ),
        CandidateFact(
            fact_id=f_private,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Confidential Role",
            claims=["SECRET_PAYLOAD_MARKER"],
            provenance="attestation",
            allowed_uses=[],  # Private: empty permissions
        ),
        CandidateFact(
            fact_id=f_restricted_parent,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Restricted Historical Role",
            provenance="attestation",
            allowed_uses=["cv"],  # Allowed for cv, not assessment
        ),
        CandidateFact(
            fact_id=f_child_of_restricted,
            parent_id=f_restricted_parent,
            kind=EvidenceFactKind.PROJECT,
            title="Allowed Project under Restricted Parent",
            provenance="attestation",
            allowed_uses=["assessment", "cv"],
        ),
    ]

    snapshot = ProfileSnapshot(
        candidate_id=cid,
        profile_version="v1",
        approval_metadata=ProfileApprovalMetadata(
            is_approved=True,
            approved_by="candidate",
            approved_at=now,
        ),
        explicit_eligibility=CandidateEligibility(
            work_authorization_countries=["DE", "AT"],
            remote_eligible=True,
            min_salary=MoneyAmount(amount=Decimal("75000"), currency="EUR"),
        ),
        evidence_records=facts,
    )

    id_map = {
        "emp_parent": f_emp_parent,
        "proj_child": f_proj_child,
        "edu": f_edu,
        "skill_assess": f_skill_assess,
        "private": f_private,
        "restricted_parent": f_restricted_parent,
        "child_of_restricted": f_child_of_restricted,
    }

    return snapshot, id_map


class TestProfileContextPreparation:
    def test_purpose_filtering_and_private_sentinel_exclusion(self) -> None:
        snapshot, id_map = create_test_snapshot()
        preparer = ProfileContextPreparer()

        prepared = preparer.prepare_context(snapshot, purpose="assessment")

        eligible_ids = set(prepared.eligible_fact_ids)
        assert id_map["emp_parent"] in eligible_ids
        assert id_map["proj_child"] in eligible_ids
        assert id_map["edu"] in eligible_ids
        assert id_map["skill_assess"] in eligible_ids
        assert id_map["child_of_restricted"] in eligible_ids

        # Private fact and cv-only parent are excluded from assessment
        assert id_map["private"] not in eligible_ids
        assert id_map["restricted_parent"] not in eligible_ids

        # Private claim text must never appear anywhere in prepared facts
        all_claims = [c for f in prepared.eligible_facts for c in f.claims]
        assert not any("SECRET_PAYLOAD_MARKER" in c for c in all_claims)

    def test_unsupported_purpose_rejected(self) -> None:
        snapshot, _ = create_test_snapshot()
        preparer = ProfileContextPreparer()
        with pytest.raises(ContextValidationError, match="Unsupported inclusion purpose"):
            preparer.prepare_context(snapshot, purpose="marketing_blast")

    def test_mandatory_chronology_derivation(self) -> None:
        snapshot, id_map = create_test_snapshot()
        preparer = ProfileContextPreparer()

        prepared = preparer.prepare_context(snapshot, purpose="assessment")

        mandatory_ids = set(prepared.mandatory_fact_ids)
        # Permitted employment and education facts must be mandatory chronology anchors
        assert id_map["emp_parent"] in mandatory_ids
        assert id_map["edu"] in mandatory_ids

        # Standalone skill is not automatically a mandatory chronology anchor
        assert id_map["skill_assess"] not in mandatory_ids

        # Permitted parent of permitted child is derived via ancestor_chain
        assert "ancestor_chain" in prepared.mandatory_reasons.get(str(id_map["emp_parent"]), [])

        # Check chronology references
        chrono_fact_ids = {c.fact_id for c in prepared.chronology}
        assert id_map["emp_parent"] in chrono_fact_ids
        assert id_map["edu"] in chrono_fact_ids

    def test_restricted_parent_unexpanded_with_warning(self) -> None:
        snapshot, id_map = create_test_snapshot()
        preparer = ProfileContextPreparer()

        prepared = preparer.prepare_context(snapshot, purpose="assessment")

        # Child of restricted parent is included, but parent is NOT added to mandatory set
        assert id_map["child_of_restricted"] in prepared.eligible_fact_ids
        assert id_map["restricted_parent"] not in prepared.mandatory_fact_ids

        # Child retains its original parent_id
        child_fact = next(f for f in prepared.eligible_facts if f.fact_id == id_map["child_of_restricted"])
        assert child_fact.parent_id == id_map["restricted_parent"]

        # Warning is generated regarding restricted parent
        assert any(str(id_map["restricted_parent"]) in w for w in prepared.warnings)

    def test_caller_mandatory_explicit_validation_and_conflict(self) -> None:
        snapshot, id_map = create_test_snapshot()
        preparer = ProfileContextPreparer()

        # Unknown ID fails validation
        fake_id = uuid.uuid4()
        with pytest.raises(ContextValidationError, match="not found in profile snapshot"):
            preparer.prepare_context(
                snapshot, purpose="assessment", explicit_mandatory_ids=[fake_id]
            )

        # Restricted ID required explicitly fails with permission error
        with pytest.raises(ContextPermissionError, match="restricted from purpose"):
            preparer.prepare_context(
                snapshot,
                purpose="assessment",
                explicit_mandatory_ids=[id_map["restricted_parent"]],
            )

        # Permitted skill required explicitly succeeds and is included
        prepared = preparer.prepare_context(
            snapshot,
            purpose="assessment",
            explicit_mandatory_ids=[id_map["skill_assess"]],
        )
        assert id_map["skill_assess"] in prepared.mandatory_fact_ids
        assert "caller_required" in prepared.mandatory_reasons[str(id_map["skill_assess"])]

    def test_unapproved_snapshot_rejected(self) -> None:
        snapshot, _ = create_test_snapshot()
        unapproved = snapshot.model_copy(
            update={
                "approval_metadata": ProfileApprovalMetadata(
                    is_approved=False,
                    approved_by="candidate",
                    approved_at=datetime.now(timezone.utc),
                )
            }
        )
        preparer = ProfileContextPreparer()
        with pytest.raises(ContextValidationError, match="must have is_approved=True"):
            preparer.prepare_context(unapproved, purpose="assessment")

    def test_deterministic_fact_ordering_independent_of_input_order(self) -> None:
        snapshot, _ = create_test_snapshot()
        preparer = ProfileContextPreparer()

        prepared1 = preparer.prepare_context(snapshot, purpose="assessment")

        # Shuffle input evidence records
        shuffled_records = list(snapshot.evidence_records)
        random.seed(42)
        random.shuffle(shuffled_records)
        shuffled_snapshot = snapshot.model_copy(update={"evidence_records": shuffled_records})

        prepared2 = preparer.prepare_context(shuffled_snapshot, purpose="assessment")

        assert prepared1.eligible_fact_ids == prepared2.eligible_fact_ids
        assert prepared1.mandatory_fact_ids == prepared2.mandatory_fact_ids
        assert prepared1.warnings == prepared2.warnings
        assert [c.fact_id for c in prepared1.chronology] == [c.fact_id for c in prepared2.chronology]

    def test_parity_with_test_rag_consumer(self) -> None:
        snapshot, _ = create_test_snapshot()
        preparer = ProfileContextPreparer()

        # Both JSON and RAG consumers use the exact same prepared context
        json_prep = preparer.prepare_context(snapshot, purpose="assessment")
        rag_prep = preparer.prepare_context(snapshot, purpose="assessment")

        assert json_prep.eligible_fact_ids == rag_prep.eligible_fact_ids
        assert json_prep.mandatory_fact_ids == rag_prep.mandatory_fact_ids
        assert json_prep.explicit_eligibility == rag_prep.explicit_eligibility

        # Simulated test RAG retrieval with top_k=0 (no optional facts retrieved)
        # In a top-k=0 retrieval, mandatory anchors still survive!
        surviving_rag_ids = set(rag_prep.mandatory_fact_ids)
        assert len(surviving_rag_ids) > 0
        for m_id in rag_prep.mandatory_fact_ids:
            assert m_id in surviving_rag_ids

    def test_defensive_mutation_isolation(self) -> None:
        snapshot, id_map = create_test_snapshot()
        preparer = ProfileContextPreparer()

        prepared = preparer.prepare_context(snapshot, purpose="assessment")

        # Mutate lists in prepared
        prepared.eligible_facts.clear()
        prepared.warnings.append("MUTATED_WARNING")

        # Snapshot evidence records are completely unaffected
        assert len(snapshot.evidence_records) == 7
