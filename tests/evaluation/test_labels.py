"""Unit tests for gold label validation and finding alignment (EVAL-01-S02)."""

import uuid
import pytest

from job_automation.contracts.assessment import RequirementFinding
from job_automation.contracts.enums import FindingStatus
from job_automation.contracts.evidence import CandidateEvidenceReference, JobEvidenceReference
from job_automation.evaluation.corpus import (
    FACT_CPP_LEAD_ID,
    FACT_RESTRICTED_CV_ONLY_ID,
    build_default_synthetic_profile,
    build_canonical_synthetic_cases,
)
from job_automation.evaluation.errors import InvalidCorpusError
from job_automation.evaluation.labels import (
    align_finding_to_gold,
    validate_gold_label_integrity,
)
from job_automation.evaluation.records import (
    GoldLabelRevision,
    GoldRequirementLabel,
)


def test_validate_gold_label_rejects_unknown_fact():
    """Verify gold label citing an unknown candidate fact ID raises InvalidCorpusError."""
    corpus_cases = build_canonical_synthetic_cases()
    c1 = corpus_cases[0]
    bad_label = GoldLabelRevision(
        case_id="bad_case",
        gold_disposition=c1.gold_label.gold_disposition,
        reviewer="test",
        rationale="test",
        requirements=[
            GoldRequirementLabel(
                requirement_id="req1",
                text="Some requirement",
                source_spans=[],
                sufficient_evidence_sets=[[str(uuid.uuid4())]],  # unknown fact
                gold_status=FindingStatus.MATCH,
            )
        ],
    )
    with pytest.raises(InvalidCorpusError, match="cites unknown fact"):
        validate_gold_label_integrity(bad_label, c1.profile, c1.posting)


def test_validate_gold_label_rejects_restricted_cv_only_fact():
    """Verify gold label citing a fact restricted to 'cv' only raises InvalidCorpusError."""
    corpus_cases = build_canonical_synthetic_cases()
    c1 = corpus_cases[0]
    bad_label = GoldLabelRevision(
        case_id="bad_case",
        gold_disposition=c1.gold_label.gold_disposition,
        reviewer="test",
        rationale="test",
        requirements=[
            GoldRequirementLabel(
                requirement_id="req1",
                text="Some requirement",
                source_spans=[],
                sufficient_evidence_sets=[[FACT_RESTRICTED_CV_ONLY_ID]],  # allowed_uses=['cv']
                gold_status=FindingStatus.MATCH,
            )
        ],
    )
    with pytest.raises(InvalidCorpusError, match="lacks 'assessment' in allowed_uses"):
        validate_gold_label_integrity(bad_label, c1.profile, c1.posting)


def test_validate_gold_label_rejects_nonexistent_quotation():
    """Verify gold label with a source span quotation absent from posting text raises InvalidCorpusError."""
    corpus_cases = build_canonical_synthetic_cases()
    c1 = corpus_cases[0]
    bad_label = GoldLabelRevision(
        case_id="bad_case",
        gold_disposition=c1.gold_label.gold_disposition,
        reviewer="test",
        rationale="test",
        requirements=[
            GoldRequirementLabel(
                requirement_id="req1",
                text="Some requirement",
                source_spans=[JobEvidenceReference(posting_revision="rev_01", field_path="description_clean", quotation="THIS QUOTATION DOES NOT EXIST IN POSTING")],
                sufficient_evidence_sets=[[FACT_CPP_LEAD_ID]],
                gold_status=FindingStatus.MATCH,
            )
        ],
    )
    with pytest.raises(InvalidCorpusError, match="not found in posting"):
        validate_gold_label_integrity(bad_label, c1.profile, c1.posting)


def test_align_finding_to_gold_sufficient_support():
    """Verify finding citing all facts of a sufficient evidence set yields has_sufficient_support=True."""
    gold_req = GoldRequirementLabel(
        requirement_id="req_cpp",
        text="C++ expertise",
        sufficient_evidence_sets=[[FACT_CPP_LEAD_ID]],
        gold_status=FindingStatus.MATCH,
    )
    finding = RequirementFinding(
        requirement_id="req_cpp",
        requirement_text="C++ expertise",
        status=FindingStatus.MATCH,
        reason="Has C++ expertise",
        candidate_evidence=[
            CandidateEvidenceReference(profile_version="v1.0", fact_id=uuid.UUID(FACT_CPP_LEAD_ID))
        ],
    )
    res = align_finding_to_gold(finding, gold_req, admitted_fact_ids={FACT_CPP_LEAD_ID})
    assert res.status_matches is True
    assert res.has_sufficient_support is True
    assert res.is_unsupported_claim is False


def test_align_finding_to_gold_partial_support():
    """Verify finding citing only 1 of 2 required facts in a conjunction yields has_sufficient_support=False."""
    f1 = str(uuid.uuid4())
    f2 = str(uuid.uuid4())
    gold_req = GoldRequirementLabel(
        requirement_id="req_combo",
        text="Requires both A and B",
        sufficient_evidence_sets=[[f1, f2]],  # conjunction
        gold_status=FindingStatus.MATCH,
    )
    # Model only cites f1
    finding = RequirementFinding(
        requirement_id="req_combo",
        requirement_text="Requires both A and B",
        status=FindingStatus.MATCH,
        reason="Has part A",
        candidate_evidence=[
            CandidateEvidenceReference(profile_version="v1.0", fact_id=uuid.UUID(f1))
        ],
    )
    res = align_finding_to_gold(finding, gold_req, admitted_fact_ids={f1, f2})
    assert res.status_matches is True
    assert res.has_sufficient_support is False  # Incomplete conjunction
    assert "Incomplete evidence" in res.notes[0]
