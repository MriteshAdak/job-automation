"""Tests for availability stage coordination and negative inference safety (RUN-01-S05)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.enums import FetchOutcome, InventorySemantics, PostingAvailability
from job_automation.contracts.postings import FetchManifest, NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.identity.availability.service import AvailabilityService
from job_automation.identity.service import IdentityService
from job_automation.orchestration.availability_stage import AvailabilityStageCoordinator
from job_automation.orchestration.identity_stage import IdentityStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.sources.models import EffectiveSource
from job_automation.storage.engine import StorageEngine


class TestAvailabilityStage:
    def test_availability_processing_complete_and_partial(self, tmp_path: Path) -> None:
        db_path = tmp_path / "avail.db"
        engine = StorageEngine(db_path=db_path)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(attempt)

        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")
        ident_coord = IdentityStageCoordinator(engine, IdentityService(engine))
        avail_coord = AvailabilityStageCoordinator(engine, AvailabilityService(engine))

        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="p1")

        # Create posting in identity
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/p1",
            raw_reference="raw/p1.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="Acme Corp",
            title="Senior Engineer",
            description_clean="Clean desc",
            observed_at=now,
        )
        ident_res = ident_coord.execute_identity(req, attempt, [c06])
        job_id = list(ident_res.affected_canonical_ids)[0]

        # 1. Complete manifest with p1 observed -> sighting applied
        man_complete = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow",
            scope_id="arbeitnow_berlin",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/p1.json"],
            observed_posting_identities=["p1"],
            outcome=FetchOutcome.COMPLETE,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        cfg = SourceConfig(
            source_key="arbeitnow",
            provider="arbeitnow",
            board_id="berlin",
            acquisition_method="api",
            base_url="https://api.example.com",
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        from job_automation.sources.validation import validate_source_config
        eff_source = validate_source_config(cfg)

        res1 = avail_coord.execute_availability(
            req, attempt, {"arbeitnow": man_complete}, {"arbeitnow": eff_source}
        )
        assert res1.total_manifests_processed == 1
        assert res1.results["arbeitnow"].positive_observations_count == 1
        assert res1.results["arbeitnow"].miss_evaluations_count == 0

        # Verify job availability is active
        job = engine.canonical_jobs.get_canonical_job(job_id)
        assert job is not None
        assert job.availability == PostingAvailability.ACTIVE

        # 2. Partial manifest missing p1 -> negative inference must NEVER trigger on partial!
        man_partial = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow",
            scope_id="arbeitnow_berlin",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/partial.json"],
            observed_posting_identities=[],  # p1 missing
            outcome=FetchOutcome.PARTIAL,
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        res2 = avail_coord.execute_availability(
            req, attempt, {"arbeitnow": man_partial}, {"arbeitnow": eff_source}
        )
        assert res2.results["arbeitnow"].miss_evaluations_count == 0  # No misses on partial!

        engine.close()
