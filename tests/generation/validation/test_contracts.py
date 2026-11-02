"""Contract validation, schema adherence, and invariant tests (GEN-04-S01)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import DocumentType
from job_automation.contracts.export_schemas import export_schemas
from job_automation.generation.validation_records import (
    DocumentValidationIssue,
    DocumentValidationReport,
    DocumentValidationSettings,
    RuleOutcome,
    SEMANTIC_LIMITS_NOTICE,
    ValidatedDraftForRendering,
    ValidationContentRequirements,
    ValidationInputBinding,
    compute_policy_digest,
    compute_report_hash,
    get_content_requirements,
)

ROOT = Path(__file__).resolve().parents[3]


def test_validation_input_binding_invariants():
    binding = ValidationInputBinding(
        request_id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        draft_id=uuid.uuid4(),
        draft_version="draft:1.0",
        draft_schema_version="2.0",
        draft_hash="sha256:abc",
        receipt_id=uuid.uuid4(),
        receipt_hash="sha256:def",
        seal_id="seal-1",
        seal_hash="sha256:123",
        manifest_id="man-1",
        manifest_hash="sha256:456",
        profile_version="v1.0",
        profile_snapshot_digest="sha256:789",
        posting_revision_id=uuid.uuid4(),
        posting_revision_hash="sha256:posting",
        context_receipt_id=uuid.uuid4(),
        context_hash="sha256:ctx",
        admitted_fact_ids=[uuid.uuid4()],
        document_type=DocumentType.CV,
        purpose="cv",
        target_language="de",
        template_id="content-basic",
        template_version="1.0",
        template_content_digest="sha256:tpl",
        rule_set_id="gen04-extractive-v1",
        rule_set_version="1.0.0",
        rule_set_digest="sha256:rules",
        binding_hash="sha256:bind",
    )
    assert binding.schema_version == "1.0"
    dumped = binding.model_dump(mode="json")
    reloaded = ValidationInputBinding.model_validate(dumped)
    assert reloaded == binding


def test_validation_content_requirements_policies():
    cv_req = get_content_requirements("content-basic", DocumentType.CV)
    assert cv_req is not None
    assert cv_req.required_sections == ["experience"]
    assert cv_req.allowed_section_order == ["summary", "experience", "education", "skills"]

    letter_req = get_content_requirements("content-basic", DocumentType.COVER_LETTER)
    assert letter_req is not None
    assert letter_req.required_sections == ["experience", "closing"]
    assert letter_req.allowed_section_order == ["opening", "experience", "motivation", "closing"]


def test_document_validation_issue_invariants():
    issue = DocumentValidationIssue(
        code="metric_value_altered",
        severity="fatal",
        message="Metric value altered from source",
        claim_id="claim_1",
        source_field="metrics",
    )
    assert issue.severity == "fatal"
    assert issue.requires_human_review is True

    # Invalid code pattern fails
    with pytest.raises(ValidationError):
        DocumentValidationIssue(
            code="INVALID-CODE-UPPERCASE",
            severity="fatal",
            message="Invalid",
        )


def test_document_validation_report_invariants():
    req_id = uuid.uuid4()
    binding = ValidationInputBinding(
        request_id=req_id,
        candidate_id=uuid.uuid4(),
        canonical_job_id=uuid.uuid4(),
        draft_id=uuid.uuid4(),
        draft_version="draft:1.0",
        draft_schema_version="2.0",
        draft_hash="sha256:abc",
        receipt_id=uuid.uuid4(),
        receipt_hash="sha256:def",
        seal_id="seal-1",
        seal_hash="sha256:123",
        manifest_id="man-1",
        manifest_hash="sha256:456",
        profile_version="v1.0",
        profile_snapshot_digest="sha256:789",
        posting_revision_id=uuid.uuid4(),
        posting_revision_hash="sha256:posting",
        context_receipt_id=uuid.uuid4(),
        context_hash="sha256:ctx",
        admitted_fact_ids=[],
        document_type=DocumentType.CV,
        purpose="cv",
        target_language="de",
        template_id="content-basic",
        template_version="1.0",
        template_content_digest="sha256:tpl",
        rule_set_id="gen04-extractive-v1",
        rule_set_version="1.0.0",
        rule_set_digest="sha256:rules",
        binding_hash="sha256:bind",
    )
    now = datetime.now(timezone.utc)
    outcomes = {"rule1": RuleOutcome(rule_id="rule1", status="checked")}

    # Valid report with 0 fatal errors and allowed_for_review
    valid_report = DocumentValidationReport(
        request_id=req_id,
        draft_id=uuid.uuid4(),
        validated_draft_hash="sha256:abc",
        input_binding=binding,
        validator_version="1.0.0",
        rule_set_id="gen04-extractive-v1",
        rule_outcomes=outcomes,
        issues=[],
        fatal_count=0,
        warning_count=0,
        evaluation_status="complete",
        render_decision="allowed_for_review",
        completed_at=now,
        report_hash="sha256:report",
    )
    assert valid_report.requires_human_review is True
    assert valid_report.render_decision == "allowed_for_review"

    # Invariant: Fatal count > 0 cannot have allowed_for_review
    with pytest.raises(ValidationError, match="Cannot allow rendering when fatal errors exist"):
        DocumentValidationReport(
            request_id=req_id,
            draft_id=uuid.uuid4(),
            validated_draft_hash="sha256:abc",
            input_binding=binding,
            validator_version="1.0.0",
            rule_set_id="gen04-extractive-v1",
            rule_outcomes=outcomes,
            issues=[DocumentValidationIssue(code="fatal_err", severity="fatal", message="Fatal")],
            fatal_count=1,
            warning_count=0,
            evaluation_status="complete",
            render_decision="allowed_for_review",  # Invalid!
            completed_at=now,
            report_hash="sha256:report",
        )

    # Invariant: Incomplete evaluation cannot allow rendering
    with pytest.raises(ValidationError, match="Cannot allow rendering with incomplete evaluation status"):
        DocumentValidationReport(
            request_id=req_id,
            draft_id=uuid.uuid4(),
            validated_draft_hash="sha256:abc",
            input_binding=binding,
            validator_version="1.0.0",
            rule_set_id="gen04-extractive-v1",
            rule_outcomes=outcomes,
            issues=[],
            fatal_count=0,
            warning_count=0,
            evaluation_status="incomplete",  # Incomplete!
            render_decision="allowed_for_review",
            completed_at=now,
            report_hash="sha256:report",
        )

    # Invariant: Rule marked not_checked cannot allow rendering
    with pytest.raises(ValidationError, match="Cannot allow rendering when rules remain not_checked"):
        DocumentValidationReport(
            request_id=req_id,
            draft_id=uuid.uuid4(),
            validated_draft_hash="sha256:abc",
            input_binding=binding,
            validator_version="1.0.0",
            rule_set_id="gen04-extractive-v1",
            rule_outcomes={"r": RuleOutcome(rule_id="r", status="not_checked")},
            issues=[],
            fatal_count=0,
            warning_count=0,
            evaluation_status="complete",
            render_decision="allowed_for_review",
            completed_at=now,
            report_hash="sha256:report",
        )


def test_schema_export_completeness(tmp_path):
    out_dir = tmp_path / "schemas" / "v1"
    export_schemas(out_dir)
    expected_files = [
        "document_validation_report.schema.json",
        "document_validation_issue.schema.json",
        "validation_input_binding.schema.json",
        "validation_content_requirements.schema.json",
        "document_validation_settings.schema.json",
        "validated_draft_for_rendering.schema.json",
    ]
    for ef in expected_files:
        p = out_dir / ef
        assert p.is_file(), f"Missing exported schema {ef}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "$schema" in data
        assert "$id" in data

