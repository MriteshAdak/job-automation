"""Tests for reading and filtering rejected job assessment populations (EVAL-01-S07)."""

import uuid
from job_automation.evaluation.population_reader import read_rejected_population


def test_population_filtering_exclusions():
    """Verify comparison records, user status, and availability closures are excluded."""
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    c3 = uuid.uuid4()
    c4 = uuid.uuid4()
    c5 = uuid.uuid4()

    records = [
        # Valid reject
        {
            "canonical_job_id": c1,
            "posting_revision": "rev_1",
            "title": "C++ Engineer",
            "final_disposition": "rejected",
            "summary_reason": "Hard failure: Germany location required, posting is USA",
            "hard_failure_reasons": ["Location mismatch"],
        },
        # Excluded: comparison record
        {
            "canonical_job_id": c2,
            "posting_revision": "rev_1",
            "title": "Python Dev",
            "final_disposition": "rejected",
            "assessment_mode": "comparison",
            "summary_reason": "Comparison eval run",
        },
        # Excluded: candidate application status 'Rejected'
        {
            "canonical_job_id": c3,
            "posting_revision": "rev_1",
            "title": "Java Dev",
            "final_disposition": "rejected",
            "candidate_application_status": "Rejected",
            "summary_reason": "User rejected job",
        },
        # Excluded: availability closure
        {
            "canonical_job_id": c4,
            "posting_revision": "rev_1",
            "title": "Rust Dev",
            "final_disposition": "rejected",
            "closed_reason": "availability",
            "summary_reason": "Listing closed",
        },
        # Excluded: pending inference
        {
            "canonical_job_id": c5,
            "posting_revision": "rev_1",
            "title": "Go Dev",
            "final_disposition": "rejected",
            "execution_status": "pending",
            "summary_reason": "Running",
        },
    ]

    result = read_rejected_population(records=records)

    assert len(result.eligible_candidates) == 1
    assert result.eligible_candidates[0].canonical_job_id == c1
    assert result.eligible_candidates[0].rejection_category == "hard_failure"

    assert result.excluded_counts["comparison_records"] == 1
    assert result.excluded_counts["candidate_status_rejected"] == 1
    assert result.excluded_counts["availability_closure"] == 1
    assert result.excluded_counts["pending_inference"] == 1


def test_frame_hash_order_invariance():
    """Verify input row order does not change the calculated frame hash."""
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()

    r1 = {
        "canonical_job_id": c1,
        "posting_revision": "rev_1",
        "title": "C++ Engineer",
        "final_disposition": "rejected",
        "summary_reason": "Skill gap",
    }
    r2 = {
        "canonical_job_id": c2,
        "posting_revision": "rev_1",
        "title": "Java Engineer",
        "final_disposition": "rejected",
        "summary_reason": "Visa mismatch",
    }

    res_a = read_rejected_population(records=[r1, r2])
    res_b = read_rejected_population(records=[r2, r1])

    assert res_a.frame_hash == res_b.frame_hash

