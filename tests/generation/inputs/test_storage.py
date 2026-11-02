"""Tests for Migration 011 tables, GenerationInputRepository, and cascade delete triggers."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import ContextStrategy, DocumentType, PostingAvailability
from job_automation.contracts.generation import GenerationRequest
from job_automation.generation.errors import FreezeConflictError
from job_automation.generation.input_records import (
    AvailabilityCheck,
    FrozenGenerationOptions,
    FrozenJobSnapshot,
    FrozenProfileSnapshot,
    FrozenSeal,
    PreflightReceipt,
    compute_sha256_digest,
)
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from job_automation.storage.exceptions import DuplicateKeyError
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestInputStorage:
    def test_migration_011_creates_companion_tables(self, engine: StorageEngine) -> None:
        cursor = engine.conn.execute(
            """
            SELECT name FROM sqlite_master WHERE type='table'
            AND name IN (
                'generation_preflight_receipts',
                'generation_frozen_seals',
                'generation_frozen_snapshots',
                'generation_context_receipts'
            )
            """
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert tables == {
            "generation_preflight_receipts",
            "generation_frozen_seals",
            "generation_frozen_snapshots",
            "generation_context_receipts",
        }

    def test_protect_sealed_generation_jobs_trigger(self, engine: StorageEngine) -> None:
        """Trigger trg_protect_sealed_generation_jobs aborts deletion of a canonical job referenced by a seal."""
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        # Create C13 request in generation_requests so foreign key succeeds
        engine.generation_requests.create_request(req)

        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        # Attempting to delete the canonical job must raise SQLite abort error
        with pytest.raises(sqlite3.IntegrityError, match="Cannot delete canonical job referenced by sealed generation input"):
            engine.conn.execute(
                "DELETE FROM canonical_jobs WHERE canonical_job_id = ?",
                (str(job.canonical_job_id),),
            )

    def test_seal_immutability_and_conflict_rejection(self, engine: StorageEngine) -> None:
        job, _, _ = create_job_with_posting(engine)
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id)
        engine.generation_requests.create_request(req)

        # 1. First seal
        manifest1, err1 = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err1 is None
        assert manifest1 is not None

        # 2. Re-freeze with identical options returns same manifest
        manifest2, err2 = service.prepare_freeze(req, f"freeze:{req.request_id}:replay")
        assert err2 is None
        assert manifest2 is not None
        assert manifest1.manifest_hash == manifest2.manifest_hash

        # 3. Re-freeze with changed options raises freeze_conflict
        conflict_req = req.model_copy(update={"target_language": "en"})
        manifest3, err3 = service.prepare_freeze(conflict_req, f"freeze:{req.request_id}:diff")
        assert manifest3 is None
        assert err3 is not None
        assert err3.details.get("reason_code") == "freeze_conflict"

