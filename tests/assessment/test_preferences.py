"""Tests for soft preferences evaluation (MATCH-01-S06)."""

from __future__ import annotations

import pytest

from job_automation.assessment.preferences import evaluate_all_preferences, evaluate_preference_rule
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.policy import PreferenceRule


class TestPreferences:
    def test_preference_match_and_evidence(self, make_posting, make_policy) -> None:
        posting = make_posting(
            workplace_type=WorkplaceType.REMOTE,
            title="Senior Python Architect",
        )
        pref_remote = PreferenceRule(
            rule_id="pref_remote",
            name="Remote Preferred",
            field="workplace_type",
            weight=0.8,
            preferred_values=["remote"],
        )
        pref_python = PreferenceRule(
            rule_id="pref_python",
            name="Python in Title",
            field="title",
            weight=0.6,
            preferred_values=["Python"],
        )

        policy = make_policy(preferences=[pref_remote, pref_python])
        outcomes = evaluate_all_preferences(policy, posting, posting.raw_content_hash)
        assert len(outcomes) == 2

        assert outcomes[0].rule_id == "pref_remote"
        assert outcomes[0].matched is True
        assert outcomes[0].weight == 0.8
        assert outcomes[0].job_evidence is not None

        assert outcomes[1].rule_id == "pref_python"
        assert outcomes[1].matched is True
        assert outcomes[1].weight == 0.6
        assert outcomes[1].job_evidence is not None

    def test_unmatched_preference_does_not_fail(self, make_posting, make_policy) -> None:
        posting = make_posting(workplace_type=WorkplaceType.ONSITE)
        pref_remote = PreferenceRule(
            rule_id="pref_remote",
            name="Remote Preferred",
            field="workplace_type",
            weight=0.8,
            preferred_values=["remote"],
        )
        policy = make_policy(preferences=[pref_remote])
        outcomes = evaluate_all_preferences(policy, posting, posting.raw_content_hash)
        assert len(outcomes) == 1
        assert outcomes[0].matched is False
        assert outcomes[0].is_unknown is False

