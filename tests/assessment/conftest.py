"""Shared fixtures and test helpers for MATCH-01 assessment tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from job_automation.contracts.enums import (
    EmploymentType,
    EvidenceFactKind,
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.policy import (
    HardCriterion,
    PreferenceRule,
    RelevanceConfig,
    SearchPolicy,
)
from job_automation.contracts.postings import (
    JobCompensation,
    NormalizedPosting,
    StructuredLocation,
)
from job_automation.contracts.primitives import PrecisionDate, SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    CandidateFact,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.policy.models import EffectiveMissingAction, EffectivePolicy, PolicyMetadata
from job_automation.policy.service import PolicyService


@pytest.fixture
def make_posting():
    """Factory fixture for synthetic NormalizedPosting."""
    def _create(
        title: str = "Python Backend Developer",
        company: str = "Acme Corp",
        description: str = "We are seeking a Python backend developer with Django and SQL experience.",
        country: str | None = "DE",
        city: str | None = "Berlin",
        workplace_type: WorkplaceType = WorkplaceType.HYBRID,
        remote_restrictions: list[str] | None = None,
        compensation: JobCompensation | None = None,
        employment_type: EmploymentType = EmploymentType.FULL_TIME,
        advert_language: str = "en",
        source_key: SourceKey | None = None,
        raw_hash: str = "sha256:" + "a" * 64,
    ) -> NormalizedPosting:
        now = datetime.now(timezone.utc)
        sk = source_key or SourceKey(provider="arbeitnow", board_id="default", source_posting_id=str(uuid.uuid4()))
        locations: list[StructuredLocation] = []
        if country or city:
            locations.append(
                StructuredLocation(
                    raw_text=f"{city or ''}, {country or ''}".strip(", "),
                    country=country,
                    city=city,
                )
            )

        return NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0-test",
            raw_reference="test/ref.json",
            raw_content_hash=raw_hash,
            company_name_hint=company,
            title=title,
            description_clean=description,
            source_url="https://example.com/job/1",
            locations=locations,
            workplace_type=workplace_type,
            remote_eligibility_restrictions=remote_restrictions or [],
            employment_type=employment_type,
            compensation=compensation,
            advert_language=advert_language,
            observed_at=now,
        )

    return _create


@pytest.fixture
def make_profile():
    """Factory fixture for approved ProfileSnapshot."""
    def _create(
        candidate_id: uuid.UUID | None = None,
        version: str = "v1",
        is_approved: bool = True,
        auth_countries: list[str] | None = None,
        remote_eligible: bool = True,
        facts: list[CandidateFact] | None = None,
    ) -> ProfileSnapshot:
        cid = candidate_id or uuid.uuid4()
        now = datetime.now(timezone.utc)
        approval = ProfileApprovalMetadata(
            is_approved=is_approved,
            approved_by="Candidate Self",
            approved_at=now,
        )
        eligibility = CandidateEligibility(
            work_authorization_countries=auth_countries if auth_countries is not None else ["DE", "EU"],
            remote_eligible=remote_eligible,
        )

        default_facts = [
            CandidateFact(
                fact_id=uuid.uuid4(),
                kind=EvidenceFactKind.EMPLOYMENT,
                title="Senior Python Developer",
                organization="Tech Corp",
                start_date=PrecisionDate(value="2020", precision="year"),
                claims=["Built scalable REST APIs in Python", "Authorized to work in Germany"],
                skills=["Python", "PostgreSQL", "Docker"],
                provenance="test_intake",
                allowed_uses=["assessment", "cv"],
            )
        ]

        return ProfileSnapshot(
            candidate_id=cid,
            profile_version=version,
            approval_metadata=approval,
            explicit_eligibility=eligibility,
            evidence_records=facts if facts is not None else default_facts,
        )

    return _create


@pytest.fixture
def make_policy():
    """Factory fixture for SearchPolicy and EffectivePolicy."""
    def _create(
        hard_criteria: list[HardCriterion] | None = None,
        preferences: list[PreferenceRule] | None = None,
        exclusions: list[str] | None = None,
        broad_keywords: list[str] | None = None,
        negative_keywords: list[str] | None = None,
        role_aliases: dict[str, list[str]] | None = None,
        skill_aliases: dict[str, list[str]] | None = None,
        missing_behavior: dict[str, str] | None = None,
        policy_version: str = "policy-v1:sha256:" + "0" * 64,
        min_score_threshold: float | None = None,
    ) -> EffectivePolicy:
        policy = SearchPolicy(
            policy_version=policy_version,
            regions=["DE"],
            role_aliases=role_aliases or {"Backend Developer": ["Python Developer", "Software Engineer"]},
            skill_aliases=skill_aliases or {"Python": ["Python 3", "Django"]},
            hard_criteria=hard_criteria or [
                HardCriterion(
                    criterion_id="crit_country",
                    name="Location Country",
                    field="locations.country",
                    operator="equals",
                    expected_value="DE",
                    on_missing="unknown",
                )
            ],
            preferences=preferences or [],
            exclusions=exclusions or [],
            missing_information_behavior=missing_behavior or {},
            relevance_configuration=RelevanceConfig(
                broad_keywords=broad_keywords if broad_keywords is not None else ["Python", "Backend"],
                negative_keywords=negative_keywords or [],
                min_score_threshold=min_score_threshold,
            ),
        )

        missing_actions: dict[str, EffectiveMissingAction] = {}
        for c in policy.hard_criteria:
            if c.on_missing in {"pass", "fail"}:
                act = c.on_missing
                src = "explicit_rule"
            elif c.field in policy.missing_information_behavior:
                act = policy.missing_information_behavior[c.field]
                src = "field_default"
            else:
                act = "unknown"
                src = "global_default"
            missing_actions[c.criterion_id] = EffectiveMissingAction(action=act, source=src)

        meta = PolicyMetadata(
            authored_version=policy_version,
            effective_version=policy_version,
        )

        return EffectivePolicy(
            policy=policy,
            metadata=meta,
            effective_missing_actions=missing_actions,
            canonical_bytes=policy.model_dump_json().encode("utf-8"),
        )

    return _create
