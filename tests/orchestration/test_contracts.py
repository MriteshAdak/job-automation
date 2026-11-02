"""Tests for RUN-01-S01 execution contracts, records, and serialization."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.enums import (
    AssessmentDisposition,
    ContextStrategy,
    RunStatus,
)
from job_automation.contracts.errors import ClassifiedError, ErrorCategory, ValidationIssue
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.runs import RunSummary
from job_automation.orchestration.records import (
    AssessmentMode,
    AssessmentSelection,
    OwnerKind,
    PostingBinding,
    QuarantineRecord,
    RunAttempt,
    RunReport,
    RunRequest,
    StageWorkRecord,
    WorkItemState,
)
from job_automation.orchestration.settings import RunSettings


class TestOrchestrationContracts:
    def test_run_request_serialization(self) -> None:
        run_id = uuid.uuid4()
        req = RunRequest(
            run_id=run_id,
            assessment_mode=AssessmentMode.RULES,
            source_keys=["arbeitnow", "manual"],
            primary_strategy=ContextStrategy.JSON,
            app_config_hash="abc123hash",
            policy_fingerprint="pol456hash",
            profile_snapshot_hash="prof789hash",
            availability_policy_hash="avail101hash",
            sync_mapping_hash="sync202hash",
            run_settings_hash="set303hash",
        )
        json_str = req.model_dump_json()
        restored = RunRequest.model_validate_json(json_str)

        assert restored.run_id == run_id
        assert restored.assessment_mode == AssessmentMode.RULES
        assert restored.source_keys == ["arbeitnow", "manual"]
        assert restored.primary_strategy == ContextStrategy.JSON
        assert restored.app_config_hash == "abc123hash"
        assert restored.policy_fingerprint == "pol456hash"
        assert restored.profile_snapshot_hash == "prof789hash"

    def test_run_attempt_serialization(self) -> None:
        run_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        attempt = RunAttempt(
            attempt_id=attempt_id,
            run_id=run_id,
            attempt_sequence=1,
            status="running",
            started_at=now,
        )
        assert attempt.attempt_id == attempt_id
        assert attempt.attempt_sequence == 1
        assert attempt.exit_code is None

        # Update with error
        err = ClassifiedError.from_category(
            category=ErrorCategory.VALIDATION,
            message="Test failure",
            details={"key": "val"},
        )
        attempt_failed = attempt.model_copy(
            update={"status": "failed", "exit_code": 1, "error": err, "completed_at": now}
        )
        dumped = json.loads(attempt_failed.model_dump_json())
        assert dumped["status"] == "failed"
        assert dumped["exit_code"] == 1
        assert dumped["error"]["message"] == "Test failure"

    def test_stage_work_record_lifecycle(self) -> None:
        run_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        work = StageWorkRecord(
            run_id=run_id,
            attempt_id=attempt_id,
            stage_name="fetch",
            work_key="source:arbeitnow",
            input_fingerprint="fp123",
            state=WorkItemState.PENDING,
        )
        assert work.state == WorkItemState.PENDING
        assert work.output_id is None

        work_done = work.model_copy(
            update={
                "state": WorkItemState.COMPLETED,
                "output_id": "manifest-arbeitnow-1",
                "checkpoint_data": {"pages": 2},
            }
        )
        assert work_done.state == WorkItemState.COMPLETED
        assert work_done.checkpoint_data == {"pages": 2}

    def test_posting_binding_record(self) -> None:
        can_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="123")
        c06 = NormalizedPosting(
            source_key=sk,
            normalizer_version="1.0",
            source_url="https://example.com/jobs/123",
            raw_reference="raw/arbeitnow/berlin/123.json",
            raw_content_hash=f"sha256:{'a'*64}",
            company_name_hint="Tech Corp",
            title="Python Developer",
            description_clean="Build software in Python",
            observed_at=datetime.now(timezone.utc),
        )
        binding = PostingBinding(
            canonical_job_id=can_id,
            revision_id=rev_id,
            normalized_content_hash=f"sha256:{'b'*64}",
            raw_reference="raw/arbeitnow/berlin/123.json",
            raw_content_hash=f"sha256:{'a'*64}",
            source_key=sk,
            c06_snapshot=c06,
        )
        assert binding.canonical_job_id == can_id
        assert binding.revision_id == rev_id
        assert binding.c06_snapshot.title == "Python Developer"

    def test_assessment_selection_record(self) -> None:
        can_id = uuid.uuid4()
        cand_id = uuid.uuid4()
        asmt_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        sel = AssessmentSelection(
            canonical_job_id=can_id,
            candidate_id=cand_id,
            purpose="assessment",
            input_fingerprint="asmtfp123",
            assessment_id=asmt_id,
            evaluated_at=now,
            generation_token="gen_1",
            is_selected_final=True,
            disposition=AssessmentDisposition.ELIGIBLE,
        )
        assert sel.is_selected_final is True
        assert sel.generation_token == "gen_1"
        assert sel.disposition == AssessmentDisposition.ELIGIBLE

    def test_quarantine_record(self) -> None:
        sk = SourceKey(provider="arbeitnow", board_id="berlin", source_posting_id="bad_1")
        issue = ValidationIssue(
            field_path="title",
            code="missing_field",
            message="Title is mandatory",
            severity="error",
        )
        q = QuarantineRecord(
            run_id=uuid.uuid4(),
            source_key=sk,
            raw_reference="raw/bad.json",
            record_index=0,
            issues=[issue],
        )
        assert len(q.issues) == 1
        assert q.issues[0].code == "missing_field"

    def test_run_settings_fingerprint_and_defaults(self, tmp_path) -> None:
        s1 = RunSettings()
        assert s1.assessment_mode == AssessmentMode.RULES
        assert s1.sync_enabled is True
        fp1 = s1.compute_fingerprint()
        assert len(fp1) == 64

        # Settings file round-trip
        sf = tmp_path / "run.json"
        sf.write_text(s1.model_dump_json(indent=2), encoding="utf-8")
        s2 = RunSettings.load_from_file(sf)
        assert s2.compute_fingerprint() == fp1

        # Changing option changes fingerprint
        s3 = s1.model_copy(update={"assessment_mode": AssessmentMode.LLM})
        assert s3.compute_fingerprint() != fp1
