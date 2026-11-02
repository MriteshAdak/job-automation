"""Tests for frozen input binding and provenance verification (GEN-04-S02)."""
from __future__ import annotations

import uuid

import pytest

from job_automation.generation.input_records import compute_sha256_digest


def test_intact_draft_passes_binding_verification(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.error is None
    assert res.report is not None
    assert res.report.fatal_count == 0
    assert res.report.render_decision == "allowed_for_review"


def test_tampered_request_id_fails_binding(setup_validation):
    env = setup_validation()
    other_request_id = uuid.uuid4()
    res = env.validation_service.validate_content(other_request_id, env.draft)
    assert res.error is not None or (res.report and res.report.fatal_count > 0)


def test_tampered_seal_hash_fails_binding(setup_validation):
    env = setup_validation()
    tampered_provenance = env.draft.provenance.model_copy(update={"seal_hash": "sha256:tampered"})
    tampered_draft = env.draft.model_copy(update={"provenance": tampered_provenance})

    res = env.validation_service.validate_content(env.request.request_id, tampered_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"
    codes = [i.code for i in res.report.issues]
    assert "provenance_binding_mismatch" in codes


def test_tampered_binding_hash_fails_binding(setup_validation):
    env = setup_validation()
    tampered_provenance = env.draft.provenance.model_copy(update={"binding_hash": "sha256:tampered"})
    tampered_draft = env.draft.model_copy(update={"provenance": tampered_provenance})

    res = env.validation_service.validate_content(env.request.request_id, tampered_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"
    codes = [i.code for i in res.report.issues]
    assert "provenance_binding_mismatch" in codes


def test_tampered_frozen_inputs_profile_version_fails(setup_validation):
    env = setup_validation()
    tampered_frozen = env.draft.frozen_inputs.model_copy(update={"profile_version": "v999.0"})
    tampered_draft = env.draft.model_copy(update={"frozen_inputs": tampered_frozen})

    res = env.validation_service.validate_content(env.request.request_id, tampered_draft)
    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"

