"""Tests for strong evidence matching, distinct requisitions, and board isolation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService, MatchOutcome
from job_automation.storage.engine import StorageEngine


def make_norm(
    provider: str,
    board_id: str,
    posting_id: str,
    title: str = "Backend Python Developer",
    company: str = "Starlight Media GmbH",
    desc: str = "Build scalable web backends with FastAPI.",
    app_url: str | None = None,
    req_id: str | None = None,
) -> NormalizedPosting:
    prov = {"requisition_id": req_id} if req_id else {}
    return NormalizedPosting(
        source_key=SourceKey(provider=provider, board_id=board_id, source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint=company,
        title=title,
        description_clean=desc,
        source_url=f"https://{provider}.example.com/jobs/{posting_id}",
        application_url=app_url,
        observed_at=datetime.now(timezone.utc),
        field_provenance=prov,
    )


class TestStrongMatching:
    def test_different_boards_with_identical_source_ids_are_distinct(
        self, tmp_path: Path
    ) -> None:
        """Postings with identical ID on different boards must remain separate canonical jobs."""
        db_path = tmp_path / "boards_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p_board_a = make_norm(
                provider="arbeitnow",
                board_id="board_alpha",
                posting_id="ID_0007",
                title="Cloud Infrastructure Architect",
                company="Company A",
                desc="Kubernetes and Terraform cloud automation.",
            )
            p_board_b = make_norm(
                provider="arbeitnow",
                board_id="board_beta",
                posting_id="ID_0007",
                title="Embedded Firmware Developer",
                company="Company B",
                desc="C and RTOS development for microcontrollers.",
            )

            res_a = service.resolve_and_commit(p_board_a)
            res_b = service.resolve_and_commit(p_board_b)

            assert res_a.canonical_job_id != res_b.canonical_job_id
            assert res_a.outcome == MatchOutcome.NEW_CANONICAL
            assert res_b.outcome == MatchOutcome.NEW_CANONICAL

    def test_distinct_requisitions_prevent_merging(self, tmp_path: Path) -> None:
        """Differing explicit requisitions must NOT be merged despite identical text and employer."""
        db_path = tmp_path / "reqs_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            identical_text = "Develop real-time data streaming pipelines in Apache Kafka."
            p1 = make_norm(
                provider="greenhouse",
                board_id="default",
                posting_id="gh_1",
                company="Nexus Systems GmbH",
                desc=identical_text,
                req_id="REQ-2026-001",
            )
            p2 = make_norm(
                provider="lever",
                board_id="default",
                posting_id="lev_1",
                company="Nexus Systems GmbH",
                desc=identical_text,
                req_id="REQ-2026-002",
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            # Different requisitions remain distinct opportunities
            assert res1.canonical_job_id != res2.canonical_job_id
            assert res1.outcome == MatchOutcome.NEW_CANONICAL
            assert res2.outcome == MatchOutcome.NEW_CANONICAL

    def test_matching_requisitions_link_as_alternate_source(self, tmp_path: Path) -> None:
        """Matching employer and requisition number link as alternate sources."""
        db_path = tmp_path / "matching_reqs_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p1 = make_norm(
                provider="greenhouse",
                board_id="default",
                posting_id="gh_10",
                company="Global Analytics AG",
                req_id="REQ-9999",
            )
            p2 = make_norm(
                provider="stepstone",
                board_id="default",
                posting_id="st_20",
                company="Global Analytics AG",
                req_id="REQ-9999",
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            # Linked to the same canonical job
            assert res1.canonical_job_id == res2.canonical_job_id
            assert res1.outcome == MatchOutcome.NEW_CANONICAL
            assert res2.outcome == MatchOutcome.STRONG_KEY_MATCH

            # Both source keys are tracked
            job = engine.canonical_jobs.get_canonical_job(res1.canonical_job_id)
            assert job is not None
            assert len(job.linked_source_keys) == 2
            assert p1.source_key in job.linked_source_keys
            assert p2.source_key in job.linked_source_keys

    def test_job_specific_application_url_matching(self, tmp_path: Path) -> None:
        """Matching job-specific application URL under same employer links as alternate source."""
        db_path = tmp_path / "matching_url_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            specific_app_url = "https://boards.greenhouse.io/acme/jobs/5551234"
            p1 = make_norm(
                provider="source_one",
                board_id="main",
                posting_id="100",
                company="Acme Corp",
                app_url=specific_app_url,
            )
            p2 = make_norm(
                provider="source_two",
                board_id="feed",
                posting_id="200",
                company="Acme Corp",
                app_url=specific_app_url,
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            assert res1.canonical_job_id == res2.canonical_job_id
            assert res2.outcome == MatchOutcome.STRONG_KEY_MATCH

    def test_generic_careers_url_does_not_merge(self, tmp_path: Path) -> None:
        """Generic careers page URL (e.g. /careers) does NOT cause automatic merging."""
        db_path = tmp_path / "generic_url_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            generic_url = "https://example.com/careers"
            p1 = make_norm(
                provider="source_one",
                board_id="main",
                posting_id="100",
                title="Frontend Developer",
                company="Acme Corp",
                app_url=generic_url,
            )
            p2 = make_norm(
                provider="source_two",
                board_id="feed",
                posting_id="200",
                title="DevOps Engineer",
                company="Acme Corp",
                app_url=generic_url,
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            assert res1.canonical_job_id != res2.canonical_job_id
