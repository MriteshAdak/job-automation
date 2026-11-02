"""Tests ensuring review import never alters candidate truth or policy (EVAL-01-S06)."""

from pathlib import Path
import pytest

from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.errors import InputTamperingError
from job_automation.evaluation.repository import EvaluationRepository
from job_automation.evaluation.review_import import import_review_corrections


def test_review_cannot_mutate_candidate_profile(tmp_path: Path):
    """Verify attempts to mutate candidate profile truth raise InputTamperingError."""
    db_path = tmp_path / "eval_privacy.db"
    repo = EvaluationRepository(db_path)
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    # Tampering payload 1: key mutate_profile
    tampering_data = [
        {
            "case_id": case.case_id,
            "reviewer_id": "malicious_actor",
            "target_type": "model_finding",
            "old_value": {},
            "new_value": {},
            "reason": "Injecting unapproved skill",
            "mutate_profile": True,
        }
    ]

    with pytest.raises(InputTamperingError, match="cannot mutate candidate profile truth"):
        import_review_corrections(tampering_data, repo, case.profile, case.policy)

    # Tampering payload 2: target_type profile_fact
    tampering_data_2 = [
        {
            "case_id": case.case_id,
            "reviewer_id": "malicious_actor",
            "target_type": "profile_fact",
            "old_value": {},
            "new_value": {"skill": "Rust"},
            "reason": "Adding Rust to candidate profile",
        }
    ]

    with pytest.raises(InputTamperingError, match="Direct profile modifications via review import are forbidden"):
        import_review_corrections(tampering_data_2, repo, case.profile, case.policy)

    repo.close()


def test_review_cannot_mutate_search_policy(tmp_path: Path):
    """Verify attempts to mutate search policy rules raise InputTamperingError."""
    db_path = tmp_path / "eval_policy_tamper.db"
    repo = EvaluationRepository(db_path)
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    tampering_data = [
        {
            "case_id": case.case_id,
            "reviewer_id": "malicious_actor",
            "target_type": "policy_rule",
            "old_value": {},
            "new_value": {"min_salary": 0},
            "reason": "Lowering salary threshold",
        }
    ]

    with pytest.raises(InputTamperingError, match="Direct policy modifications via review import are forbidden"):
        import_review_corrections(tampering_data, repo, case.profile, case.policy)

    repo.close()

