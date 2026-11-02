"""Tests for profile validation, parent hierarchy graph, date consistency, and permissions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.profile.errors import ProfileValidationError
from job_automation.profile.models import DraftFact, DraftProfile
from job_automation.profile.validation import (
    compare_precision_dates,
    validate_draft,
    validate_facts_graph,
    validate_snapshot,
)


class TestProfileValidation:
    def test_duplicate_fact_ids_rejected(self) -> None:
        fid = uuid.uuid4()
        f1 = DraftFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Engineer A",
        )
        f2 = DraftFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Engineer B",
        )
        with pytest.raises(ProfileValidationError, match="Duplicate fact_id"):
            validate_facts_graph([f1, f2])

    def test_self_referential_parent_rejected(self) -> None:
        fid = uuid.uuid4()
        fact = DraftFact(
            fact_id=fid,
            parent_id=fid,
            kind=EvidenceFactKind.PROJECT,
            title="Self Parent",
        )
        with pytest.raises(ProfileValidationError, match="Self-referential parent_id"):
            validate_facts_graph([fact])

    def test_missing_parent_rejected(self) -> None:
        fid = uuid.uuid4()
        missing_pid = uuid.uuid4()
        fact = DraftFact(
            fact_id=fid,
            parent_id=missing_pid,
            kind=EvidenceFactKind.PROJECT,
            title="Orphan Project",
        )
        with pytest.raises(ProfileValidationError, match="Parent fact .* does not exist"):
            validate_facts_graph([fact])

    def test_cyclic_parent_relationship_rejected(self) -> None:
        f1_id = uuid.uuid4()
        f2_id = uuid.uuid4()
        f3_id = uuid.uuid4()

        # Cycle: f1 -> f2 -> f3 -> f1
        f1 = DraftFact(fact_id=f1_id, parent_id=f2_id, kind=EvidenceFactKind.PROJECT, title="P1")
        f2 = DraftFact(fact_id=f2_id, parent_id=f3_id, kind=EvidenceFactKind.PROJECT, title="P2")
        f3 = DraftFact(fact_id=f3_id, parent_id=f1_id, kind=EvidenceFactKind.PROJECT, title="P3")

        with pytest.raises(ProfileValidationError, match="Cyclic parent relationship"):
            validate_facts_graph([f1, f2, f3])

    def test_invalid_calendar_date_rejected(self) -> None:
        fid = uuid.uuid4()
        # 2021-02-31 is invalid calendar date
        fact = DraftFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Dev",
            start_date=PrecisionDate(value="2021-02-31", precision="day"),
        )
        with pytest.raises(ProfileValidationError, match="Invalid calendar date"):
            validate_facts_graph([fact])

    def test_start_date_after_end_date_rejected(self) -> None:
        fid = uuid.uuid4()
        fact = DraftFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Dev",
            start_date=PrecisionDate(value="2023-05", precision="month"),
            end_date=PrecisionDate(value="2022-01", precision="month"),
        )
        with pytest.raises(ProfileValidationError, match="Date range invalid"):
            validate_facts_graph([fact])

    def test_unsupported_allowed_use_rejected(self) -> None:
        fid = uuid.uuid4()
        fact = DraftFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Dev",
            allowed_uses=["cv", "automatic_application"],
        )
        with pytest.raises(ProfileValidationError, match="Unsupported allowed_use 'automatic_application'"):
            validate_facts_graph([fact])

    def test_precision_date_comparison_helper(self) -> None:
        d_2020 = PrecisionDate(value="2020", precision="year")
        d_2021 = PrecisionDate(value="2021", precision="year")
        d_2021_05 = PrecisionDate(value="2021-05", precision="month")
        d_2021_06 = PrecisionDate(value="2021-06", precision="month")
        d_2021_05_10 = PrecisionDate(value="2021-05-10", precision="day")
        d_2021_05_20 = PrecisionDate(value="2021-05-20", precision="day")

        assert compare_precision_dates(d_2020, d_2021) == -1
        assert compare_precision_dates(d_2021, d_2020) == 1
        assert compare_precision_dates(d_2021_05, d_2021_06) == -1
        assert compare_precision_dates(d_2021_05_10, d_2021_05_20) == -1
        assert compare_precision_dates(d_2021_05, d_2021) == 0  # overlapping at year level

    def test_snapshot_requires_is_approved_true(self) -> None:
        candidate_id = uuid.uuid4()
        approval = ProfileApprovalMetadata(
            is_approved=False,
            approved_by="candidate",
            approved_at=datetime.now(timezone.utc),
        )
        snapshot = ProfileSnapshot(
            candidate_id=candidate_id,
            profile_version="v1",
            approval_metadata=approval,
            explicit_eligibility=CandidateEligibility(),
            evidence_records=[],
        )
        with pytest.raises(ProfileValidationError, match="is_approved=True"):
            validate_snapshot(snapshot)

