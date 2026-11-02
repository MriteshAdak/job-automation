"""Tests for end-to-end deterministic discovery and assessment pipeline slice (RUN-01-S06)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from job_automation.assessment.service import AssessmentService
from job_automation.contracts.enums import AssessmentDisposition, FetchOutcome, InventorySemantics
from job_automation.contracts.policy import SearchPolicy
from job_automation.contracts.postings import FetchManifest, SourceJobDraft
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.profile import CandidateEligibility, ProfileApprovalMetadata, ProfileSnapshot
from job_automation.contracts.sources import SourceConfig
from job_automation.identity.availability.service import AvailabilityService
from job_automation.identity.service import IdentityService
from job_automation.ingestion.normalization.service import DefaultNormalizer
from job_automation.orchestration.assessment_stage import AssessmentStageCoordinator
from job_automation.orchestration.availability_stage import AvailabilityStageCoordinator
from job_automation.orchestration.identity_stage import IdentityStageCoordinator
from job_automation.orchestration.invalidation import InvalidationEvaluator
from job_automation.orchestration.normalize_stage import NormalizeStageCoordinator
from job_automation.orchestration.records import RunAttempt, RunRequest
from job_automation.orchestration.selection import SelectionManager
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine


class TestDeterministicPipelineSlice:
    def test_deterministic_slice_execution(self, tmp_path: Path) -> None:
        db_path = tmp_path / "slice.db"
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(parents=True)
        engine = StorageEngine(db_path=db_path, raw_dir=raw_dir)
        engine.initialize_schema()

        run_id = uuid.uuid4()
        engine.runs.create_run(run_id=run_id)
        attempt = RunAttempt(run_id=run_id, attempt_sequence=1, status="running")
        engine.pipeline_work.save_run_attempt(attempt)

        req = RunRequest(run_id=run_id, app_config_hash="cfg_hash")

        # 1. Prepare drafts
        now = datetime.now(timezone.utc)
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="101")
        normalizer = DefaultNormalizer()
        normalizer.register_raw_payload("raw/101.json", b'{"title": "Dev"}')

        draft = SourceJobDraft(
            source_key=sk,
            fetch_time=now,
            raw_reference="raw/101.json",
            original_fields={},
            source_mapped_fields={
                "title": "Software Developer",
                "company_name_hint": "Example GmbH",
                "description": "Python, Linux, and databases.",
                "source_url": "https://example.com/job/101",
                "observed_at": now.isoformat(),
            },
        )

        # 2. Normalize
        norm_coord = NormalizeStageCoordinator(engine, normalizer)
        norm_res = norm_coord.execute_normalization(req, attempt, [(draft, "raw/101.json", 0)])
        assert len(norm_res.normalized_postings) == 1

        # 3. Identity
        ident_coord = IdentityStageCoordinator(engine, IdentityService(engine))
        ident_res = ident_coord.execute_identity(req, attempt, norm_res.normalized_postings)
        assert ident_res.canonical_jobs_new == 1
        assert len(ident_res.bindings) == 1
        binding = ident_res.bindings[0]

        # 4. Availability
        avail_coord = AvailabilityStageCoordinator(engine, AvailabilityService(engine))
        man = FetchManifest(
            run_id=run_id,
            source_key="arbeitnow",
            scope_id="arbeitnow_berlin",
            start_time=now,
            end_time=now,
            page_count=1,
            raw_response_refs=["raw/101.json"],
            observed_posting_identities=["101"],
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
        eff = validate_source_config(cfg)
        avail_res = avail_coord.execute_availability(
            req, attempt, {"arbeitnow": man}, {"arbeitnow": eff}
        )
        assert avail_res.total_manifests_processed == 1

        # 5. Assess
        cand_id = uuid.uuid4()
        profile = ProfileSnapshot(
            candidate_id=cand_id,
            profile_version="v1",
            approval_metadata=ProfileApprovalMetadata(
                is_approved=True,
                approved_by="Candidate",
                approved_at=now,
            ),
            explicit_eligibility=CandidateEligibility(),
            evidence_records=[],
        )
        policy = SearchPolicy(
            policy_version="v1",
            hard_criteria=[],
            preferences=[],
            exclusions=[],
        )
        asmt_coord = AssessmentStageCoordinator(
            engine=engine,
            assessment_service=AssessmentService(),
            selection_manager=SelectionManager(engine),
            invalidation_evaluator=InvalidationEvaluator(engine),
        )
        asmt_res = asmt_coord.execute_assessment(
            request=req,
            attempt=attempt,
            bindings=[binding],
            profile=profile,
            policy=policy,
        )

        assert asmt_res.total_evaluated == 1
        assert len(asmt_res.items) == 1
        assert asmt_res.items[0].assessment.final_disposition in (
            AssessmentDisposition.ELIGIBLE,
            AssessmentDisposition.REVIEW,
        )
        assert asmt_res.items[0].selection.is_selected_final is True

        engine.close()
