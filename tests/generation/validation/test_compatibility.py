"""Tests for legacy compatibility and unsupported version rejection (GEN-04-S01)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.artifacts import DraftDocument
from job_automation.contracts.draft_content import read_draft_json
from job_automation.contracts.enums import DocumentApproval, DocumentType
from job_automation.generation.records import FreezeManifest, ValidationReport
from job_automation.generation.validation_adapter import DraftValidatorV2


def test_legacy_c14_v1_readable_but_rejected_by_v2_validator(setup_validation):
    env = setup_validation()

    from job_automation.contracts.generation import FrozenInputVersions

    v1_draft = DraftDocument(
        request_id=env.request.request_id,
        document_type=DocumentType.CV,
        document_version="1.0",
        title="Generated CV",
        candidate_name="Max Mustermann",
        target_role="Software Engineer",
        target_company="Acme Corp",
        frozen_inputs=FrozenInputVersions(
            posting_revision="rev-1",
            profile_version="v1",
            policy_version="p1",
            template_version="t1",
        ),
    )
    manifest, _ = env.inputs.prepare_freeze(env.request, "compat-freeze")

    report, err = env.validator_adapter.validate_draft(v1_draft, manifest)
    assert report is None
    assert err is not None
    assert "DraftValidatorV2 only supports C14 DraftDocumentV2" in err.message


def test_unsupported_c14_version_raises():
    unsupported_json = json.dumps({"schema_version": "99.0", "data": "bad"})
    with pytest.raises(ValueError, match="Unsupported C14 content version"):
        read_draft_json(unsupported_json)

