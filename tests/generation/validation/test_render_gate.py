"""Tests for exact-content render authorization gate and envelopes (GEN-04-S06)."""
from __future__ import annotations

import pytest

from job_automation.generation.input_records import compute_sha256_digest


def test_prepare_render_input_succeeds_on_valid_report(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None

    envelope, report = env.validation_service.prepare_render_input(env.request.request_id, env.draft)
    assert envelope is not None
    assert report is not None
    assert envelope.render_decision == "allowed_for_review"
    assert envelope.requires_human_review is True
    assert envelope.draft_hash == compute_sha256_digest(env.draft)
    assert envelope.report_id == res.report.report_id
    assert envelope.report_hash == res.report.report_hash
    # All attached issues must be warnings only
    assert all(w.severity == "warning" for w in envelope.review_warnings)


def test_prepare_render_input_blocked_when_fatal_errors_exist(setup_validation):
    env = setup_validation()
    # Create a draft with a fatal error
    bad_claims = list(env.draft.claims)
    bad_claims[0] = bad_claims[0].model_copy(update={"text": "Rewritten non-source text"})
    bad_draft = env.draft.model_copy(update={"claims": bad_claims})

    res = env.validation_service.validate_content(env.request.request_id, bad_draft)
    assert res.report is not None
    assert res.report.render_decision == "blocked"

    envelope, report = env.validation_service.prepare_render_input(env.request.request_id, bad_draft)
    assert envelope is None
    assert report is not None
    assert report.render_decision == "blocked"


def test_prepare_render_input_blocked_when_draft_hash_differs(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None

    # Alter draft after validation
    altered_draft = env.draft.model_copy(update={"document_version": "draft:tampered"})
    envelope, report = env.validation_service.prepare_render_input(env.request.request_id, altered_draft)

    assert envelope is None
    assert report is not None


def test_prepare_render_input_returns_none_when_no_report(setup_validation):
    env = setup_validation()
    envelope, report = env.validation_service.prepare_render_input(env.request.request_id, env.draft)
    assert envelope is None
    assert report is None

