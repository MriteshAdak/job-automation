"""Tests for atomic resolution transactions and fault injection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService
from job_automation.storage.engine import StorageEngine
from job_automation.storage.repositories.identity import IdentityRepository


def make_posting(posting_id: str = "atomic_1") -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider="manual", board_id="default", source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint="Atomicity Corp",
        title="Site Reliability Engineer",
        description_clean="Ensure high availability and fault tolerance.",
        source_url="https://example.com/sre/1",
        observed_at=datetime.now(timezone.utc),
    )


class TestAtomicService:
    def test_atomic_commit_persists_all_related_entities(self, tmp_path: Path) -> None:
        db_path = tmp_path / "atomic_success.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p = make_posting("atom_10")
            res = service.resolve_and_commit(p)

            # 1. Canonical job exists
            job = engine.canonical_jobs.get_canonical_job(res.canonical_job_id)
            assert job is not None
            assert job.company_name == "Atomicity Corp"

            # 2. Revisions exist
            revs = engine.canonical_jobs.get_revisions(res.canonical_job_id)
            assert len(revs) == 1
            assert revs[0].revision_id == res.revision.revision_id

            # 3. Source identity exists
            can_id = engine.identity.get_canonical_id_for_source_key(p.source_key)
            assert can_id == res.canonical_job_id

            # 4. Observation exists
            obs = engine.identity.get_observations(res.canonical_job_id)
            assert len(obs) == 1
            assert obs[0]["observation_id"] == str(res.observation_id)

    def test_fault_before_commit_rolls_back_all_partial_state(self, tmp_path: Path) -> None:
        """Simulated crash/exception before transaction commit leaves no orphan rows."""
        db_path = tmp_path / "atomic_fault.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p = make_posting("atom_fault")

            # Inject a failure inside save_observation (after canonical job and source identity were written)
            with patch.object(
                IdentityRepository,
                "save_observation",
                side_effect=RuntimeError("Simulated database disk failure!"),
            ):
                with pytest.raises(RuntimeError, match="Simulated database disk failure!"):
                    service.resolve_and_commit(p)

            # Transaction must be rolled back: no canonical job, no source identity, no observation
            job = engine.canonical_jobs.find_by_source_key(p.source_key)
            assert job is None

            can_id = engine.identity.get_canonical_id_for_source_key(p.source_key)
            assert can_id is None

            all_jobs = engine.canonical_jobs.list_jobs()
            assert len(all_jobs) == 0

    def test_replay_idempotency(self, tmp_path: Path) -> None:
        """Calling resolve_and_commit repeatedly with identical input produces stable state."""
        db_path = tmp_path / "replay_idem.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            p = make_posting("atom_replay")
            res1 = service.resolve_and_commit(p)
            res2 = service.resolve_and_commit(p)

            assert res1.canonical_job_id == res2.canonical_job_id
            assert res1.revision.revision_id == res2.revision.revision_id

            all_jobs = engine.canonical_jobs.list_jobs()
            assert len(all_jobs) == 1
