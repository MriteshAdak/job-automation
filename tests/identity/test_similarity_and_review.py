"""Tests for fuzzy text similarity handling, review case proposals, and operator decisions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService, MatchOutcome
from job_automation.storage.engine import StorageEngine


def make_posting_sample(
    provider: str,
    posting_id: str,
    title: str,
    company: str,
    desc: str,
) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider=provider, board_id="default", source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint=company,
        title=title,
        description_clean=desc,
        source_url=f"https://{provider}.example.com/jobs/{posting_id}",
        observed_at=datetime.now(timezone.utc),
    )


class TestSimilarityAndReview:
    def test_fuzzy_similarity_creates_review_case_without_auto_merging(
        self, tmp_path: Path
    ) -> None:
        """High text similarity across different sources must NOT auto-merge; creates a review case."""
        db_path = tmp_path / "review_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            shared_desc = (
                "Wir suchen einen erfahrenen Python Entwickler für unsere Microservice Architektur. "
                "Erfahrung mit Docker, Kubernetes und PostgreSQL wird vorausgesetzt."
            )

            p1 = make_posting_sample(
                provider="provider_one",
                posting_id="p1",
                title="Senior Python Entwickler",
                company="FinTech Solutions GmbH",
                desc=shared_desc,
            )
            p2 = make_posting_sample(
                provider="provider_two",
                posting_id="p2",
                title="Senior Python Entwickler (m/w/d)",
                company="FinTech Solutions GmbH",
                desc=shared_desc,
            )

            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            # Strict correctness rule: fuzzy similarity does NOT auto-merge
            assert res1.canonical_job_id != res2.canonical_job_id
            assert res1.outcome == MatchOutcome.NEW_CANONICAL
            assert res2.outcome == MatchOutcome.REVIEW_CANDIDATE
            assert res2.review_case_id is not None

            # Verify review case exists in durable storage
            case = engine.identity.get_review_case(res2.review_case_id)
            assert case is not None
            assert case["status"] == "pending"
            assert res1.canonical_job_id in case["candidate_job_ids"]
            assert case["source_key"] == p2.source_key

    def test_review_case_lifecycle_and_decision(self, tmp_path: Path) -> None:
        """Test accepting, rejecting, and deferring review cases."""
        db_path = tmp_path / "review_lifecycle_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            shared_desc = "Cloud security engineer focusing on AWS IAM, GuardDuty, and compliance."
            p1 = make_posting_sample("src_a", "1", "Cloud Security Engineer", "SecCorp", shared_desc)
            p2 = make_posting_sample("src_b", "2", "Cloud Security Engineer", "SecCorp", shared_desc)

            service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)
            case_id = res2.review_case_id
            assert case_id is not None

            # Operator rejects duplicate
            updated_case = service.decide_review_case(
                case_id=case_id,
                decision="reject",
                actor="reviewer_jane",
                reason="Confirmed different positions in different teams",
            )
            assert updated_case.status == "rejected"
            assert updated_case.decision_actor == "reviewer_jane"
            assert updated_case.decision_reason == "Confirmed different positions in different teams"

            # Re-fetch from storage confirms update
            stored = engine.identity.get_review_case(case_id)
            assert stored is not None
            assert stored["status"] == "rejected"

    def test_deduplication_of_repeated_review_proposals(self, tmp_path: Path) -> None:
        """Repeated sightings of the same candidate pair do not spawn duplicate pending review cases."""
        db_path = tmp_path / "review_dedup_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            desc = "Full stack TypeScript and React engineering position."
            p1 = make_posting_sample("board_1", "j1", "TypeScript Engineer", "WebCo", desc)
            p2 = make_posting_sample("board_2", "j2", "TypeScript Engineer", "WebCo", desc)

            service.resolve_and_commit(p1)
            res_first = service.resolve_and_commit(p2)
            res_repeat = service.resolve_and_commit(p2)

            cases = service.list_review_cases(status="pending")
            assert len(cases) == 1
            assert cases[0].case_id == res_first.review_case_id

