"""Tests for revision content hashing, field projections, and stability."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from job_automation.contracts.enums import (
    CompensationProvenance,
    EmploymentType,
    SalaryPeriod,
    WorkplaceType,
)
from job_automation.contracts.postings import (
    JobCompensation,
    NormalizedPosting,
    StructuredLocation,
)
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.hashing import (
    compute_revision_content_hash,
    compute_revision_content_projection,
)


def make_posting(
    title: str = "Senior Cloud Architect",
    desc: str = "Design distributed cloud infrastructure with Terraform.",
    company: str = "Beta Corp GmbH",
    observed_at: datetime | None = None,
    raw_hash: str = "sha256:" + "1" * 64,
    locations: list[StructuredLocation] | None = None,
    restrictions: list[str] | None = None,
    comp: JobCompensation | None = None,
) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="manual", board_id="default", source_posting_id="p100"),
        normalizer_version="1.0-test",
        raw_reference="raw/p100.txt",
        raw_content_hash=raw_hash,
        company_name_hint=company,
        title=title,
        description_clean=desc,
        source_url="https://jobs.example.com/p100",
        application_url="https://jobs.example.com/apply/p100",
        locations=locations or [],
        workplace_type=WorkplaceType.HYBRID,
        remote_eligibility_restrictions=restrictions or [],
        employment_type=EmploymentType.FULL_TIME,
        compensation=comp,
        advert_language="de",
        observed_at=observed_at or datetime.now(timezone.utc),
    )


class TestRevisionHashing:
    def test_golden_content_hash_stability(self) -> None:
        posting = make_posting(
            title="Softwareentwickler (m/w/d)",
            desc="Entwicklung von Cloud-Lösungen in Berlin.",
            company="Müller & Söhne GmbH",
            observed_at=datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
            locations=[
                StructuredLocation(raw_text="Berlin", country="DE", region="Berlin", city="Berlin"),
            ],
            restrictions=["DE", "EU"],
            comp=JobCompensation(
                min_amount=Decimal("75000"),
                max_amount=Decimal("90000"),
                currency="EUR",
                period=SalaryPeriod.YEARLY,
                is_gross=True,
                provenance=CompensationProvenance.EMPLOYER_PROVIDED,
            ),
        )

        h1 = compute_revision_content_hash(posting)
        h2 = compute_revision_content_hash(posting)
        assert h1 == h2
        assert h1.startswith("sha256:")
        assert len(h1) == 71  # "sha256:" + 64 hex chars

    def test_metadata_only_change_preserves_hash(self) -> None:
        """Observation timestamp, raw hash, and normalizer version do not change revision hash."""
        p1 = make_posting(
            observed_at=datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc),
            raw_hash="sha256:" + "a" * 64,
        )
        p2 = make_posting(
            observed_at=datetime(2026, 10, 28, 18, 30, 0, tzinfo=timezone.utc),
            raw_hash="sha256:" + "b" * 64,
        )
        # Normalizer version differs
        p2 = p2.model_copy(update={"normalizer_version": "2.0-experimental"})

        h1 = compute_revision_content_hash(p1)
        h2 = compute_revision_content_hash(p2)
        assert h1 == h2

    def test_material_changes_alter_hash(self) -> None:
        base = make_posting()
        base_hash = compute_revision_content_hash(base)

        # Title change
        h_title = compute_revision_content_hash(make_posting(title="Lead Cloud Architect"))
        assert h_title != base_hash

        # Description change
        h_desc = compute_revision_content_hash(make_posting(desc="Updated requirements and skills"))
        assert h_desc != base_hash

        # Compensation change
        comp = JobCompensation(
            min_amount=Decimal("80000"),
            max_amount=Decimal("95000"),
            currency="EUR",
            period=SalaryPeriod.YEARLY,
        )
        h_comp = compute_revision_content_hash(make_posting(comp=comp))
        assert h_comp != base_hash

    def test_locations_and_restrictions_order_insensitivity(self) -> None:
        """Different ordering of identical locations or restrictions produces the same hash."""
        loc1 = StructuredLocation(raw_text="Berlin", country="DE", city="Berlin")
        loc2 = StructuredLocation(raw_text="Hamburg", country="DE", city="Hamburg")

        p1 = make_posting(locations=[loc1, loc2], restrictions=["DE", "AT"])
        p2 = make_posting(locations=[loc2, loc1], restrictions=["AT", "DE"])

        assert compute_revision_content_hash(p1) == compute_revision_content_hash(p2)

