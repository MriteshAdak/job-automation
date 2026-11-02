"""Tests for importing reviewer corrections and validation guards (EVAL-01-S06)."""

from pathlib import Path
import uuid
import pytest

from job_automation.evaluation.corpus import EvaluationCorpus
from job_automation.evaluation.errors import (
    InvalidCorpusError,
    UnadjudicatedReviewError,
)
from job_automation.evaluation.repository import EvaluationRepository
from job_automation.evaluation.review_import import import_review_corrections


def test_import_valid_correction_and_idempotency(tmp_path: Path):
    """Verify importing a valid correction and checking idempotent re-import."""
    db_path = tmp_path / "eval_corrections.db"
    repo = EvaluationRepository(db_path)
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    valid_fact_id = str(case.profile.evidence_records[0].fact_id)

    correction_data = [
        {
            "case_id": case.case_id,
            "reviewer_id": "reviewer_alice",
            "target_type": "model_finding",
            "old_value": {"status": "match"},
            "new_value": {"status": "gap"},
            "reason": "Insufficient seniority demonstrated",
            "supporting_evidence": [
                {
                    "source_kind": "candidate",
                    "profile_version": case.profile.profile_version,
                    "fact_id": valid_fact_id,
                }
            ],
            "active_review_seconds": 32.5,
            "adjudication_status": "adjudicated",
        }
    ]

    # First import
    imported = import_review_corrections(correction_data, repo, case.profile, case.policy)
    assert len(imported) == 1
    assert repo.list_corrections(case.case_id)[0].reviewer_id == "reviewer_alice"

    # Second import (idempotent no-op)
    reimported = import_review_corrections(correction_data, repo, case.profile, case.policy)
    assert len(reimported) == 0
    assert len(repo.list_corrections(case.case_id)) == 1

    repo.close()


def test_conflicting_unadjudicated_corrections_fail(tmp_path: Path):
    """Verify conflicting unadjudicated corrections raise UnadjudicatedReviewError."""
    db_path = tmp_path / "eval_corrections_conflict.db"
    repo = EvaluationRepository(db_path)
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    c1 = [
        {
            "case_id": case.case_id,
            "reviewer_id": "reviewer_alice",
            "target_type": "model_finding",
            "old_value": {"status": "match"},
            "new_value": {"status": "gap"},
            "reason": "Alice claims gap",
            "adjudication_status": "pending",
        }
    ]
    import_review_corrections(c1, repo, case.profile, case.policy)

    c2 = [
        {
            "case_id": case.case_id,
            "reviewer_id": "reviewer_bob",
            "target_type": "model_finding",
            "old_value": {"status": "match"},
            "new_value": {"status": "match"},
            "reason": "Bob claims match",
            "adjudication_status": "pending",
        }
    ]

    with pytest.raises(UnadjudicatedReviewError, match="Conflicting unadjudicated corrections"):
        import_review_corrections(c2, repo, case.profile, case.policy)

    repo.close()


def test_unknown_fact_citation_fails(tmp_path: Path):
    """Verify citing unknown fact in supporting evidence raises InvalidCorpusError."""
    db_path = tmp_path / "eval_corrections_unknown.db"
    repo = EvaluationRepository(db_path)
    corpus = EvaluationCorpus.default_synthetic()
    case = corpus.get_case("case_01_eligible_senior_cpp")

    bad_correction = [
        {
            "case_id": case.case_id,
            "reviewer_id": "reviewer_alice",
            "target_type": "label_error",
            "old_value": {},
            "new_value": {},
            "reason": "Cite non-existent fact",
            "supporting_evidence": [
                {
                    "source_kind": "candidate",
                    "profile_version": case.profile.profile_version,
                    "fact_id": "99999999-9999-9999-9999-999999999999",
                }
            ],
            "adjudication_status": "adjudicated",
        }
    ]

    with pytest.raises(InvalidCorpusError, match="unknown candidate fact ID"):
        import_review_corrections(bad_correction, repo, case.profile, case.policy)

    repo.close()

