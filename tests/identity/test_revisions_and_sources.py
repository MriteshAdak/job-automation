"""Tests for repeated postings, changed descriptions, and alternate source retention."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService, MatchOutcome
from job_automation.storage.engine import StorageEngine


def make_norm_posting(
    posting_id: str,
    desc: str,
    title: str = "Lead Software Architect",
    company: str = "Pinnacle Tech",
    source_url: str = "https://pinnacle.example.com/job/1",
    app_url: str | None = None,
    observed_at: datetime | None = None,
) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint=company,
        title=title,
        description_clean=desc,
        source_url=source_url,
        application_url=app_url,
        observed_at=observed_at or datetime.now(timezone.utc),
    )


class TestRevisionsAndSources:
    def test_repeated_posting_same_content(self, tmp_path: Path) -> None:
        """Re-sighting same posting with identical content reuses canonical UUID and revision UUID."""
        db_path = tmp_path / "repeated_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            t1 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc)

            p1 = make_norm_posting(posting_id="101", desc="Initial job description", observed_at=t1)
            p2 = make_norm_posting(posting_id="101", desc="Initial job description", observed_at=t2)

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            # Reuses same canonical ID and same revision ID
            assert res1.canonical_job_id == res2.canonical_job_id
            assert res1.revision.revision_id == res2.revision.revision_id
            assert res1.outcome == MatchOutcome.NEW_CANONICAL
            assert res2.outcome == MatchOutcome.EXACT_SOURCE_SAME_CONTENT
            assert res2.is_new_canonical is False
            assert res2.is_new_revision is False

            # Advances last_seen_at
            job = engine.canonical_jobs.get_canonical_job(res1.canonical_job_id)
            assert job is not None
            assert job.first_seen_at == t1
            assert job.last_seen_at == t2
            assert len(job.revisions) == 1

            # Observations recorded
            obs = engine.identity.get_observations(job.canonical_job_id)
            assert len(obs) == 2

    def test_changed_description_creates_new_revision(self, tmp_path: Path) -> None:
        """Edited description under same source tuple creates a new revision under the same job."""
        db_path = tmp_path / "changed_desc_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            t1 = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc)

            p1 = make_norm_posting(
                posting_id="102",
                desc="Version 1: Python, Django, Docker.",
                observed_at=t1,
            )
            p2 = make_norm_posting(
                posting_id="102",
                desc="Version 2: Python, FastAPI, Kubernetes, AWS.",
                observed_at=t2,
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            # Same canonical job UUID, but NEW revision UUID
            assert res1.canonical_job_id == res2.canonical_job_id
            assert res1.revision.revision_id != res2.revision.revision_id
            assert res2.outcome == MatchOutcome.EXACT_SOURCE_NEW_REVISION
            assert res2.is_new_revision is True

            # Job maintains both revisions and current_revision_id points to the newer one
            job = engine.canonical_jobs.get_canonical_job(res1.canonical_job_id)
            assert job is not None
            assert len(job.revisions) == 2
            assert job.current_revision_id == res2.revision.revision_id
            assert job.first_seen_at == t1
            assert job.last_seen_at == t2

            # Historical revision 1 is still intact and resolvable
            revs = engine.canonical_jobs.get_revisions(job.canonical_job_id)
            assert len(revs) == 2
            assert any(r.revision_id == res1.revision.revision_id for r in revs)
            assert any(r.revision_id == res2.revision.revision_id for r in revs)

    def test_multiple_source_urls_and_application_urls_retained(self, tmp_path: Path) -> None:
        """When multiple URLs are observed for a posting, historical links are accumulated."""
        db_path = tmp_path / "urls_accum_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            t1 = datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

            p1 = make_norm_posting(
                posting_id="103",
                desc="Core description",
                source_url="https://example.com/job/103",
                app_url="https://example.com/apply/v1",
                observed_at=t1,
            )
            p2 = make_norm_posting(
                posting_id="103",
                desc="Core description",
                source_url="https://example.com/job/103",
                app_url="https://example.com/apply/v2",
                observed_at=t2,
            )

            service.resolve_and_commit(p1)
            service.resolve_and_commit(p2)

            job = engine.canonical_jobs.find_by_source_key(p1.source_key)
            assert job is not None
            current_rev = next(r for r in job.revisions if r.revision_id == job.current_revision_id)
            assert "https://example.com/apply/v1" in current_rev.application_urls
            assert "https://example.com/apply/v2" in current_rev.application_urls
