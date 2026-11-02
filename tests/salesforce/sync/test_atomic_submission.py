"""Atomic submission validation and error handling tests for SYNC-01 (SYNC-01-S04)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.assessment import Assessment
from job_automation.contracts.enums import PostingAvailability
from job_automation.salesforce.sync_errors import (
    StaleSelectionError,
    SyncMappingError,
    SyncValidationError,
)
from job_automation.salesforce.sync_records import (
    PublicationPurpose,
    SyncSubmission,
)
from job_automation.salesforce.sync_service import SyncService
from job_automation.salesforce.sync_settings import (
    SyncMappingConfig,
    load_sync_mapping_config,
)
from job_automation.storage.engine import StorageEngine

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "salesforce" / "sync"
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "sync.example.json"


def load_c11_fixture(filename: str) -> Assessment:
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Assessment.model_validate(data)


class TestAtomicSubmission:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "sync_atomic_test.db"
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def config(self) -> SyncMappingConfig:
        return load_sync_mapping_config(CONFIG_FILE)

    def _ensure_canonical_job(
        self,
        engine: StorageEngine,
        job_id: uuid.UUID,
        company_name: str = "Cloud Corp",
        company_id: uuid.UUID | None = None,
    ) -> None:
        now_dt = datetime.now(timezone.utc)
        from job_automation.contracts.identity import CanonicalJob
        job = CanonicalJob(
            canonical_job_id=job_id,
            canonical_company_id=company_id,
            company_name=company_name,
            current_revision_id=uuid.uuid4(),
            first_seen_at=now_dt,
            last_seen_at=now_dt,
        )
        engine.canonical_jobs.save_canonical_job(job)

    def test_stale_generation_token_rejected(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        self._ensure_canonical_job(engine, job_id, "Cloud Corp")
        service = SyncService(engine)

        # Register active generation token as 'gen-v2'
        service.register_selection_token(job_id, "gen-v2")

        # Attempt to submit late completion with older token 'gen-v1'
        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-v1",  # Stale!
            company_name="Cloud Corp",
            canonical_company_id=uuid.uuid4(),
        )

        with pytest.raises(StaleSelectionError, match="is stale; active generation is 'gen-v2'"):
            service.commit_assessment_and_plan(sub, config)

    def test_missing_canonical_company_id_raises_sync_mapping_error(
        self, engine: StorageEngine, config: SyncMappingConfig
    ) -> None:
        asm = load_c11_fixture("rules_only_eligible.json")
        job_id = asm.canonical_job_id
        self._ensure_canonical_job(engine, job_id, "Mystery Corp")
        service = SyncService(engine)

        now_dt = datetime.now(timezone.utc)
        sub = SyncSubmission(
            assessment=asm,
            canonical_job_id=job_id,
            posting_revision=asm.posting_revision,
            evaluated_at=now_dt,
            generation_token="gen-1",
            company_name="Mystery Corp",
            canonical_company_id=None,  # Missing!
        )

        with pytest.raises(SyncMappingError, match="without stable canonical_company_id"):
            service.commit_assessment_and_plan(sub, config)
