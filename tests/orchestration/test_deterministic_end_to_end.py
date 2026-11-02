"""End-to-end integration tests for deterministic manual pipeline execution (RUN-01-S08)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    InventorySemantics,
    PostingAvailability,
    RunStatus,
)
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import (
    CandidateEligibility,
    ProfileApprovalMetadata,
    ProfileSnapshot,
)
from job_automation.contracts.sources import SourceConfig
from job_automation.orchestration.runner import PipelineRunner, RunOptions
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.fakes.salesforce_sync import FakeSalesforceGatewayV2


class TestDeterministicEndToEnd:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> StorageEngine:
        db_path = tmp_path / "e2e_data" / "job_automation.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        eng = StorageEngine(db_path=db_path)
        eng.initialize_schema()
        yield eng
        eng.close()

    @pytest.fixture
    def candidate_profile(self) -> ProfileSnapshot:
        now = datetime.now(timezone.utc)
        return ProfileSnapshot(
            candidate_id=uuid.uuid4(),
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="Candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(
                work_authorization_countries=["DE"],
                remote_eligible=True,
            ),
            evidence_records=[],
        )

    @pytest.fixture
    def search_policy(self) -> SearchPolicy:
        return SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )

    def test_deterministic_pipeline_full_cycle_and_unchanged_rerun(
        self,
        tmp_path: Path,
        engine: StorageEngine,
        candidate_profile: ProfileSnapshot,
        search_policy: SearchPolicy,
    ) -> None:
        data_root = tmp_path / "e2e_data"
        gateway = FakeSalesforceGatewayV2()

        # Seed 1 source
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="job-101")
        cfg = SourceConfig(
            source_key="arbeitnow:berlin",
            provider="arbeitnow",
            board_id="berlin",
            acquisition_method="api",
            base_url="https://www.arbeitnow.com/api/job-board-api",
            inventory_semantics=InventorySemantics.COMPLETE_BOARD,
        )
        eff_source = validate_source_config(cfg)

        runner = PipelineRunner(
            data_root=data_root,
            engine=engine,
        )

        opts = RunOptions(
            assessment_mode="rules",
            enable_sync=True,
            run_candidate_backup=False,
            gateway=gateway,
        )

        # -------------------------------------------------------------
        # Run 1: Initial Execution
        # -------------------------------------------------------------
        report1 = runner.start_run(
            options=opts,
            profile_override=candidate_profile,
            policy_override=search_policy,
            effective_sources_override=[eff_source],
        )

        # Empty complete fetch on synthetic source yields success with 0 discovery counts
        assert report1.exit_code == 0
        assert report1.c15_summary.status == RunStatus.SUCCESS
        assert report1.c15_summary.source_postings_count == 0
        assert report1.c15_summary.canonical_jobs_new == 0

        # Now let's insert a valid raw draft and normalized posting into storage
        # to test end-to-end data processing with sync
        now = datetime.now(timezone.utc)
        can_id = uuid.uuid4()
        comp_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        rev_hash = f"sha256:{'d'*64}"

        cjob = CanonicalJob(
            canonical_job_id=can_id,
            canonical_company_id=comp_id,
            company_name="EndToEnd Tech GmbH",
            availability=PostingAvailability.ACTIVE,
            current_revision_id=rev_id,
            first_seen_at=now,
            last_seen_at=now,
            revisions=[
                PostingRevision(
                    revision_id=rev_id,
                    canonical_job_id=can_id,
                    source_key=sk,
                    content_hash=rev_hash,
                    title="Principal Python Architect",
                    first_seen_at=now,
                    last_seen_at=now,
                    source_urls=["https://example.com/job/101"],
                    availability=PostingAvailability.ACTIVE,
                )
            ],
        )
        engine.canonical_jobs.save_canonical_job(cjob)

        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/job/101",
            raw_reference="raw/101.json",
            raw_content_hash=f"sha256:{'1'*64}",
            company_name_hint="EndToEnd Tech GmbH",
            title="Principal Python Architect",
            description_clean="Python architect description",
            observed_at=now,
        )
        engine.canonical_jobs.save_normalized_posting(c06)

        # -------------------------------------------------------------
        # Run 2: Seeded posting execution through identity, assessment, and sync
        # -------------------------------------------------------------
        # Re-run with normalized postings
        report2 = runner.start_run(
            options=opts,
            profile_override=candidate_profile,
            policy_override=search_policy,
            effective_sources_override=[],
        )

        assert report2.exit_code == 0
        assert report2.c15_summary.status == RunStatus.SUCCESS
        assert report2.stage_statuses["assessment"] == "succeeded"
        assert report2.stage_statuses["sync"] == "succeeded"

        # Verify show command reads the persisted run report accurately
        show_report = runner.show_run(report2.c15_summary.run_id)
        assert show_report is not None
        assert show_report.c15_summary.run_id == report2.c15_summary.run_id
        assert show_report.c15_summary.status == RunStatus.SUCCESS
