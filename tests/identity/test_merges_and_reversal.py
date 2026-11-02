"""Tests for reversible canonical job merge and reversal operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import (
    IdentityService,
    InvalidOperationError,
    ReversalError,
)
from job_automation.storage.engine import StorageEngine


def make_posting(
    provider: str,
    board_id: str,
    posting_id: str,
    title: str,
    company: str,
    desc: str,
    app_url: str | None = None,
) -> NormalizedPosting:
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
    )


class TestMergesAndReversal:
    def test_merge_and_reversal_lifecycle_with_post_merge_observation(
        self, tmp_path: Path
    ) -> None:
        """Merge Job A and B, record observation for B while merged, then reverse without link loss."""
        db_path = tmp_path / "merge_rev_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            # 1. Create Job A from Source 1
            p_a = make_posting(
                provider="source_one",
                board_id="main",
                posting_id="A1",
                title="Principal Software Engineer",
                company="Orion Labs GmbH",
                desc="Lead architecture for distributed systems.",
                app_url="https://orion.example.com/apply/A1",
            )
            res_a = service.resolve_and_commit(p_a)
            job_a_id = res_a.canonical_job_id

            # 2. Create Job B from Source 2
            p_b = make_posting(
                provider="source_two",
                board_id="feed",
                posting_id="B1",
                title="Principal Software Engineer",
                company="Orion Labs GmbH",
                desc="Lead architecture for distributed systems.",
                app_url="https://orion.example.com/apply/B1",
            )
            res_b = service.resolve_and_commit(p_b)
            job_b_id = res_b.canonical_job_id
            assert job_a_id != job_b_id

            # 3. Execute Merge: Job B into Job A
            merge_op = service.merge_canonical_jobs(
                surviving_id=job_a_id,
                merged_id=job_b_id,
                actor="lead_reviewer",
                reason="Adjudicated identical requisition across boards",
            )
            assert merge_op.surviving_canonical_id == job_a_id
            assert merge_op.merged_canonical_id == job_b_id

            # Inspect surviving job A
            job_a_merged = engine.canonical_jobs.get_canonical_job(job_a_id)
            assert job_a_merged is not None
            assert len(job_a_merged.linked_source_keys) == 2
            assert p_a.source_key in job_a_merged.linked_source_keys
            assert p_b.source_key in job_a_merged.linked_source_keys
            assert len(job_a_merged.revisions) == 2
            assert any("MERGE:" in line for line in job_a_merged.merge_lineage)

            # Looking up Source B now resolves to surviving Job A
            lookup_b = engine.canonical_jobs.find_by_source_key(p_b.source_key)
            assert lookup_b is not None
            assert lookup_b.canonical_job_id == job_a_id

            # 4. Receive new observation for Source B while merged
            t_during = datetime(2026, 10, 28, 15, 30, 0, tzinfo=timezone.utc)
            p_b_during = make_posting(
                provider="source_two",
                board_id="feed",
                posting_id="B1",
                title="Principal Software Engineer - Updated Requirements",
                company="Orion Labs GmbH",
                desc="Lead architecture for distributed systems (AWS, Kubernetes, Go).",
                app_url="https://orion.example.com/apply/B1",
            )
            p_b_during = p_b_during.model_copy(update={"observed_at": t_during})
            res_b_during = service.resolve_and_commit(p_b_during)
            assert res_b_during.canonical_job_id == job_a_id

            # Surviving Job A now has 3 revisions
            job_a_updated = engine.canonical_jobs.get_canonical_job(job_a_id)
            assert job_a_updated is not None
            assert len(job_a_updated.revisions) == 3

            # 5. Reverse the Merge
            reversal_op = service.reverse_merge(
                operation_id=merge_op.operation_id,
                actor="lead_reviewer",
                reason="Mistaken duplicate identification",
            )
            assert reversal_op.surviving_canonical_id == job_a_id
            assert reversal_op.restored_canonical_id == job_b_id

            # 6. Verify restored Job B
            job_b_restored = engine.canonical_jobs.get_canonical_job(job_b_id)
            assert job_b_restored is not None
            assert job_b_restored.canonical_job_id == job_b_id
            assert job_b_restored.availability == PostingAvailability.ACTIVE
            assert job_b_restored.linked_source_keys == [p_b.source_key]
            # Restored Job B has both its pre-merge revision and the one observed while merged!
            assert len(job_b_restored.revisions) == 2
            assert all(r.canonical_job_id == job_b_id for r in job_b_restored.revisions)
            assert any("REVERSAL:" in line for line in job_b_restored.merge_lineage)

            # 7. Verify restored Job A
            job_a_restored = engine.canonical_jobs.get_canonical_job(job_a_id)
            assert job_a_restored is not None
            assert job_a_restored.canonical_job_id == job_a_id
            assert job_a_restored.linked_source_keys == [p_a.source_key]
            assert len(job_a_restored.revisions) == 1
            assert all(r.canonical_job_id == job_a_id for r in job_a_restored.revisions)

            # 8. Source lookups now resolve independently to their original canonical jobs!
            lookup_a_final = engine.canonical_jobs.find_by_source_key(p_a.source_key)
            assert lookup_a_final is not None
            assert lookup_a_final.canonical_job_id == job_a_id

            lookup_b_final = engine.canonical_jobs.find_by_source_key(p_b.source_key)
            assert lookup_b_final is not None
            assert lookup_b_final.canonical_job_id == job_b_id

    def test_self_merge_prevention(self, tmp_path: Path) -> None:
        db_path = tmp_path / "self_merge_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p = make_posting("src", "b", "1", "Dev", "Co", "Text")
            res = service.resolve_and_commit(p)

            with pytest.raises(InvalidOperationError, match="Cannot merge canonical job"):
                service.merge_canonical_jobs(
                    surviving_id=res.canonical_job_id,
                    merged_id=res.canonical_job_id,
                    actor="test",
                    reason="invalid",
                )

    def test_double_reversal_rejected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "double_rev_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p1 = make_posting("s1", "b", "1", "Dev A", "Co A", "Text A")
            p2 = make_posting("s2", "b", "2", "Dev B", "Co B", "Text B")
            res1 = service.resolve_and_commit(p1)
            res2 = service.resolve_and_commit(p2)

            op = service.merge_canonical_jobs(
                res1.canonical_job_id, res2.canonical_job_id, "actor", "reason"
            )
            service.reverse_merge(op.operation_id, "actor", "first reversal")

            with pytest.raises(ReversalError, match="already reversed"):
                service.reverse_merge(op.operation_id, "actor", "second reversal")

