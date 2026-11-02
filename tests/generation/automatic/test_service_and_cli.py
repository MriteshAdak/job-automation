"""Tests for AutomaticDraftService, preview mode, and CLI commands."""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    DocumentType,
    PostingAvailability,
)
from job_automation.contracts.identity import CanonicalJob
from job_automation.generation.automatic.cli import run_auto_draft_cli
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    DocumentVariantConfig,
)
from job_automation.generation.automatic.reporting import format_evaluation_report
from job_automation.generation.automatic.service import AutomaticDraftService
from job_automation.storage.engine import StorageEngine


def _setup_engine(tmp_path: Path) -> StorageEngine:
    db_path = tmp_path / "test.db"
    artifacts_dir = tmp_path / "artifacts"
    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()
    return engine


def _make_candidate(cand_id: uuid.UUID, job_id: uuid.UUID, score: float = 85.0) -> AutomaticDraftCandidate:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    return AutomaticDraftCandidate(
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        canonical_job_id=job_id,
        assessment_id=uuid.uuid4(),
        assessment_input_fingerprint="sha256:assess_fp",
        assessment_disposition=AssessmentDisposition.ELIGIBLE,
        assessment_method="llm",
        relevance_score=score,
        score_scale="0-100",
        evaluated_at=now,
        posting_revision_id="rev-1",
        posting_revision_hash="sha256:post_rev",
        normalized_content_hash="sha256:post_norm",
        profile_version="v1.0",
        profile_digest="sha256:prof",
        search_policy_version="v1.0",
        search_policy_hash="sha256:search",
        availability_status=PostingAvailability.ACTIVE,
        availability_observed_at=now,
        candidate_application_state="New",
        candidate_opted_out=False,
        candidate_control_observed_at=now,
        run_id=uuid.uuid4(),
        run_mode="production",
        is_authoritative_selection=True,
    )


def _create_canonical_job(engine: StorageEngine, job_id: uuid.UUID, company_name: str = "Corp") -> CanonicalJob:
    now = datetime.now(timezone.utc)
    job = CanonicalJob(
        canonical_job_id=job_id,
        company_name=company_name,
        current_revision_id=uuid.uuid4(),
        first_seen_at=now,
        last_seen_at=now,
        availability=PostingAvailability.ACTIVE,
    )
    engine.canonical_jobs.save_canonical_job(job)
    return job


def test_service_preview_mode_zero_writes(tmp_path: Path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    # Prepopulate canonical job
    _create_canonical_job(engine, job_id, "Acme Corp")

    cand = _make_candidate(cand_id, job_id, score=85.0)
    policy = AutomaticDraftPolicy(
        policy_id="preview-policy",
        policy_version="v1.0",
        enabled=True,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=True)

    assert report.total_candidates_evaluated == 1
    assert report.jobs_by_outcome.get("admitted") == 1
    assert len(report.admitted_intents) == 1

    # In PREVIEW mode: zero intents, decisions, or requests written to DB!
    assert engine.automatic_drafts.get_intent_by_key(report.admitted_intents[0]) is None
    assert len(engine.automatic_drafts.list_decisions_for_job(job_id)) == 0
    assert len(engine.generation_requests.list_by_job(job_id)) == 0


def test_service_execution_mode_commits_work(tmp_path: Path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    _create_canonical_job(engine, job_id, "Acme Corp")

    cand = _make_candidate(cand_id, job_id, score=85.0)
    policy = AutomaticDraftPolicy(
        policy_id="exec-policy",
        policy_version="v1.0",
        enabled=True,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=False)

    assert report.jobs_by_outcome.get("admitted") == 1

    # In EXECUTION mode: decision, intent, reservation, request and binding must exist!
    decisions = engine.automatic_drafts.list_decisions_for_job(job_id)
    assert len(decisions) == 1
    assert decisions[0].outcome == AutomaticDraftOutcome.ADMITTED

    intents = engine.automatic_drafts.list_intents_for_job(job_id)
    assert len(intents) == 1
    assert intents[0].submission_state.value == "acknowledged"

    requests = engine.generation_requests.list_by_job(job_id)
    assert len(requests) == 1
    assert requests[0].client_request_key == intents[0].client_request_key

    binding = engine.automatic_drafts.get_binding_by_request_id(requests[0].request_id)
    assert binding is not None
    assert binding.intent_id == intents[0].intent_id


def test_safe_report_formatting(tmp_path: Path):
    engine = _setup_engine(tmp_path)
    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()

    cand = _make_candidate(cand_id, job_id, score=85.0)
    policy = AutomaticDraftPolicy(
        policy_id="test-report",
        policy_version="v1.0",
        enabled=True,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=True)

    formatted_text = format_evaluation_report(report, as_json=False)
    assert "AUTO-02 Automatic Drafting Policy Evaluation Report" in formatted_text
    assert "test-report" in formatted_text
    assert "admitted" in formatted_text

    formatted_json = format_evaluation_report(report, as_json=True)
    data = json.loads(formatted_json)
    assert data["policy_id"] == "test-report"
    assert data["total_candidates_evaluated"] == 1


def test_windows_paths_with_spaces_and_umlauts(tmp_path: Path):
    # German umlauts and spaces: e.g. "Bewerbung München & Zürich"
    special_dir = tmp_path / "Bewerbung München & Zürich"
    special_dir.mkdir(parents=True, exist_ok=True)

    db_path = special_dir / "datenbank.sqlite"
    artifacts_dir = special_dir / "artefakte"
    engine = StorageEngine(db_path=db_path, artifacts_dir=artifacts_dir)
    engine.initialize_schema()

    cand_id = uuid.uuid4()
    job_id = uuid.uuid4()
    _create_canonical_job(engine, job_id, "Münchner Software GmbH")

    cand = _make_candidate(cand_id, job_id, score=90.0)
    policy = AutomaticDraftPolicy(
        policy_id="de-policy",
        policy_version="v1.0",
        enabled=True,
        candidate_id=cand_id,
        salesforce_org_id="00D000000000001EAA",
        document_variants=[DocumentVariantConfig(document_type=DocumentType.CV)],
    )

    service = AutomaticDraftService(engine)
    report = service.evaluate_and_process(policy=policy, candidates=[cand], preview=False)
    assert report.jobs_by_outcome.get("admitted") == 1
