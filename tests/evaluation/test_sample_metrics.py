"""Tests for audit metrics and false omission proportion among rejects (EVAL-01-S07)."""

import uuid
from job_automation.contracts.enums import AssessmentDisposition
from job_automation.evaluation.records import SampleManifest
from job_automation.evaluation.sample_review import (
    SampleReviewItem,
    audit_sampled_rejects,
)


def test_false_omission_proportion_among_rejects():
    """Verify false omission proportion among rejects and unreviewed tracking."""
    id1 = "00000000-0000-0000-0000-000000000001"
    id2 = "00000000-0000-0000-0000-000000000002"
    id3 = "00000000-0000-0000-0000-000000000003"
    id4 = "00000000-0000-0000-0000-000000000004"

    manifest = SampleManifest(
        population_cohort_id="cohort_test",
        population_size=100,
        sample_size=4,
        sampling_seed=42,
        stratification_summary={"hard_failure": 60, "semantic_gap": 40},
        inclusion_probabilities={"hard_failure": 0.05, "semantic_gap": 0.05},
        selected_case_ids=[id1, id2, id3, id4],
        frame_hash="frame_hash_1",
    )

    # 4 sampled items:
    # id1: hard_failure, reviewed, correct rejection (gold REJECTED)
    # id2: hard_failure, reviewed, false omission! (gold ELIGIBLE)
    # id3: semantic_gap, reviewed, false omission! (gold REVIEW)
    # id4: semantic_gap, unreviewed!
    reviews = [
        SampleReviewItem(
            canonical_job_id=id1,
            stratum="hard_failure",
            reviewed=True,
            gold_disposition=AssessmentDisposition.REJECTED,
            defect_type="correct_rejection",
        ),
        SampleReviewItem(
            canonical_job_id=id2,
            stratum="hard_failure",
            reviewed=True,
            gold_disposition=AssessmentDisposition.ELIGIBLE,
            defect_type="evaluator_defect",
        ),
        SampleReviewItem(
            canonical_job_id=id3,
            stratum="semantic_gap",
            reviewed=True,
            gold_disposition=AssessmentDisposition.REVIEW,
            defect_type="evaluator_defect",
        ),
        SampleReviewItem(
            canonical_job_id=id4,
            stratum="semantic_gap",
            reviewed=False,
            defect_type="unreviewed",
        ),
    ]

    report = audit_sampled_rejects(manifest, reviews)

    assert report.total_sampled == 4
    assert report.total_reviewed == 3
    assert report.unreviewed_count == 1
    assert report.false_omissions_count == 2
    # 2 false omissions out of 3 reviewed = 2/3 = 0.6667
    assert report.false_omission_proportion_among_rejects == 0.6667

    # Metric limitation note explicitly prohibits calling this population FNR
    assert "NOT overall population recall or FNR" in report.metric_limitation_note
    assert hasattr(report, "false_omission_proportion_among_rejects")

