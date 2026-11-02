"""Tests for review warnings preservation and review obligations (GEN-04-S05)."""
from __future__ import annotations

import pytest


def test_upstream_review_issues_inherited_as_warnings(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)

    assert res.report is not None
    assert res.report.fatal_count == 0
    assert res.report.warning_count > 0
    assert res.report.requires_human_review is True

    warning_codes = [i.code for i in res.report.issues if i.severity == "warning"]
    assert "semantic_review_required" in warning_codes
    assert "source_language_preserved" in warning_codes
    assert "candidate_identity_missing" in warning_codes

    # Each inherited warning carries inherited_from="draft_review_issues"
    inherited = [i for i in res.report.issues if i.inherited_from == "draft_review_issues"]
    assert len(inherited) > 0


def test_warnings_only_report_allows_rendering_for_review_without_approval(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)

    assert res.report is not None
    assert res.report.fatal_count == 0
    assert res.report.render_decision == "allowed_for_review"
    assert res.report.requires_human_review is True
    # Does not claim approval or verified truth
    assert not hasattr(res.report, "is_approved")
    assert not hasattr(res.report, "truth_score")

