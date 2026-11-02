"""Tests for AUTO-02 data records, contracts, schema validation, and immutability."""

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from job_automation.contracts.enums import ContextStrategy, DocumentType
from job_automation.generation.automatic.records import (
    AutomaticDraftCandidate,
    AutomaticDraftDecision,
    AutomaticDraftEvaluationReport,
    AutomaticDraftIntent,
    AutomaticDraftOutcome,
    AutomaticDraftPolicy,
    AutomaticDraftReservation,
    AutomaticRequestBinding,
    AutomaticVolumeLimits,
    DocumentVariantConfig,
    RepeatMode,
    RepeatPolicy,
    ReservationStatus,
    SubmissionState,
    export_schemas,
)


def test_disabled_policy_default():
    candidate_id = uuid.uuid4()
    policy = AutomaticDraftPolicy(
        candidate_id=candidate_id,
        salesforce_org_id="00D000000000001EAA",
    )
    assert not policy.enabled
    assert policy.minimum_relevance_score == 75.0
    assert policy.score_scale == "0-100"
    assert policy.policy_content_hash is not None
    assert len(policy.policy_content_hash) == 64


def test_enabled_policy_validation():
    candidate_id = uuid.uuid4()

    # Enabled without document variants should fail
    with pytest.raises(ValidationError, match="at least one document variant"):
        AutomaticDraftPolicy(
            enabled=True,
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            document_variants=[],
        )

    # Enabled with duplicate document_type should fail
    with pytest.raises(ValidationError, match="duplicate document_type"):
        AutomaticDraftPolicy(
            enabled=True,
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            document_variants=[
                DocumentVariantConfig(document_type=DocumentType.CV),
                DocumentVariantConfig(document_type=DocumentType.CV),
            ],
        )

    # Enabled with empty allowed_application_states should fail
    with pytest.raises(ValidationError, match="allowed_application_states"):
        AutomaticDraftPolicy(
            enabled=True,
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            allowed_application_states=[],
            document_variants=[
                DocumentVariantConfig(document_type=DocumentType.CV),
            ],
        )


def test_policy_score_bounds_and_nan():
    candidate_id = uuid.uuid4()

    # NaN score
    with pytest.raises(ValidationError):
        AutomaticDraftPolicy(
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            minimum_relevance_score=float("nan"),
        )

    # Infinite score
    with pytest.raises(ValidationError):
        AutomaticDraftPolicy(
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            minimum_relevance_score=float("inf"),
        )

    # Score > 100
    with pytest.raises(ValidationError):
        AutomaticDraftPolicy(
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            minimum_relevance_score=105.0,
        )

    # Score < 0
    with pytest.raises(ValidationError):
        AutomaticDraftPolicy(
            candidate_id=candidate_id,
            salesforce_org_id="00D000000000001EAA",
            minimum_relevance_score=-5.0,
        )


def test_volume_limits_validation():
    # Negative limits not permitted
    with pytest.raises(ValidationError):
        AutomaticVolumeLimits(max_requests_per_run=-1)

    with pytest.raises(ValidationError):
        AutomaticVolumeLimits(window_hours=0)


def test_schema_export_completeness(tmp_path: Path):
    exported = export_schemas(tmp_path)
    assert len(exported) == 7
    for p in exported:
        assert p.is_file()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "$schema" in data
        assert "$id" in data
        assert "properties" in data

