"""Tests demonstrating that structurally valid paraphrases still require human judgment (GEN-04-S05)."""
from __future__ import annotations

import pytest

from job_automation.generation.validation_records import SEMANTIC_LIMITS_NOTICE


def test_structurally_valid_excerpts_require_human_judgment(setup_validation):
    """Even a 100% structurally valid draft with 0 fatal errors retains mandatory human review."""
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)

    assert res.report is not None
    assert res.report.fatal_count == 0
    assert res.report.render_decision == "allowed_for_review"

    # Human review invariant: MUST always be True
    assert res.report.requires_human_review is True

    # Document-wide semantic limits notice must be explicitly present
    assert res.report.semantic_limits_notice == SEMANTIC_LIMITS_NOTICE
    assert "Human semantic review remains mandatory" in res.report.semantic_limits_notice
    assert "do not certify real-world accuracy" in res.report.semantic_limits_notice

    # Semantic review issue is preserved for human attention
    review_issues = [i for i in res.report.issues if i.code == "semantic_review_required"]
    assert len(review_issues) > 0


def test_rewritten_paraphrase_fails_conservative_extraction(setup_validation):
    """Under extractive recipes, rewrites like 'contributed' -> 'led' fail code checks."""
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]

    # Suppose candidate fact claim is "Built Elixir services" or similar; rewrite it to "Led architecture of Elixir services"
    orig_text = cand_fact.claims[0]
    rewritten_text = f"Directed and led: {orig_text}"

    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "text": rewritten_text,
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    assert res.report.render_decision == "blocked"


def test_no_truth_certification_or_auto_approval_produced(setup_validation):
    """Passing validation only permits rendering for review; never approves or certifies truth."""
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)

    assert res.report is not None
    # No auto-approval
    assert res.report.render_decision == "allowed_for_review"
    assert not hasattr(res.report, "approved_at")
    assert not hasattr(res.report, "truth_score")

